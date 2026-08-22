"""Minimal client for the Biamp Tesira Text Protocol (TTP) over SSH.

Protocol reference: Biamp Cornerstone "Tesira Text Protocol" manual (v4.2).

Key facts this client relies on:
  * SSH authentication (username/password) happens at the transport layer.
    Once the SSH session is open there is no separate TTP login step.
  * The Tesira's TTP shell requires a PTY on the SSH channel: without one
    it accepts the session and sends its banner, then silently closes the
    connection the instant a command is written to stdin. Confirmed
    against a live TesiraFORTE.
  * Commands are single ASCII lines terminated with a line feed.
  * Responses start with "+OK" (success) or "-ERR" (failure, followed by
    a reason).
  * Presets are recalled by name via the DEVICE service command
    `recallPresetByName`; there is no TTP command to enumerate presets.
  * A Level Control block's fader is the "level" attribute (dB, ranged by
    its own minLevel/maxLevel), addressed by its Instance Tag and a
    channel index (`Level1 get level 1` -> `+OK "value":-10.000000`).
  * Levels can be subscribed to for push updates instead of polled: the
    device sends unsolicited lines prefixed with "!" whenever a
    subscribed value changes
    (`! "publishToken":"<token>" "value":<val>`), interleaved on the same
    stream as ordinary command responses. Subscriptions are per-session
    and are lost on reconnect, so they're re-sent after every connect().
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

import asyncssh

_LOGGER = logging.getLogger(__name__)

BANNER_IDLE_TIMEOUT = 0.5
RECONNECT_INITIAL_DELAY = 5.0
RECONNECT_MAX_DELAY = 60.0

_VALUE_RE = re.compile(r'"value"\s*:\s*(-?\d+(?:\.\d+)?)')
_PUBLISH_RE = re.compile(r'^!\s*"publishToken":"(?P<token>[^"]*)"\s*"value":(?P<value>-?\d+(?:\.\d+)?)')


class TesiraError(Exception):
    """Base error for all Tesira client failures."""


class TesiraConnectionError(TesiraError):
    """Raised when the SSH/TTP session cannot be established or is lost."""


class TesiraCommandError(TesiraError):
    """Raised when the device responds with -ERR to a command."""

    def __init__(self, command: str, response: str) -> None:
        self.command = command
        self.response = response
        super().__init__(f"{command!r} -> {response}")


def _escape_value(text: str) -> str:
    """Escape a string for use inside a double-quoted TTP Value."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _quote_tag(tag: str) -> str:
    """Quote an Instance Tag if it contains whitespace, per TTP syntax rules."""
    if re.search(r"\s", tag):
        return f'"{tag}"'
    return tag


def parse_float_value(body: str) -> float | None:
    """Extract the numeric "value":X token from a response body, if present."""
    match = _VALUE_RE.search(body)
    return float(match.group(1)) if match else None


@dataclass
class TesiraConnectionInfo:
    host: str
    port: int
    username: str
    password: str
    timeout: float = 10.0


@dataclass
class _Subscription:
    tag: str
    channel: int
    throttle_ms: int
    callback: Callable[[float], None]


class TesiraClient:
    """A TTP-over-SSH client with one in-flight command at a time, plus
    push-based level subscriptions delivered concurrently on the same
    connection.
    """

    def __init__(self, info: TesiraConnectionInfo) -> None:
        self._info = info
        self._conn: asyncssh.SSHClientConnection | None = None
        self._process: asyncssh.SSHClientProcess | None = None
        self._connect_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._pending: asyncio.Future[str] | None = None
        self._reader_task: asyncio.Task | None = None
        self._subscriptions: dict[str, _Subscription] = {}
        self._closing = False

    @property
    def connected(self) -> bool:
        return self._process is not None

    async def connect(self) -> None:
        """Open the SSH session and TTP shell channel, then re-arm any subscriptions."""
        async with self._connect_lock:
            if self.connected:
                return
            self._closing = False
            try:
                self._conn = await asyncssh.connect(
                    self._info.host,
                    port=self._info.port,
                    username=self._info.username,
                    password=self._info.password,
                    known_hosts=None,
                    login_timeout=self._info.timeout,
                )
                # A PTY is required: without one, the Tesira accepts the SSH
                # session and banner but silently drops the connection the
                # moment a command is written to stdin. Confirmed against a
                # live TesiraFORTE over SSH.
                self._process = await self._conn.create_process(term_type="dumb", encoding="utf-8")
            except (OSError, asyncssh.Error) as err:
                self._close_resources()
                raise TesiraConnectionError(
                    f"could not connect to {self._info.host}: {err}"
                ) from err

            await self._drain_banner()
            self._reader_task = asyncio.create_task(self._reader_loop())
            await self._resubscribe_all()

    async def disconnect(self) -> None:
        self._closing = True
        self._fail_pending("disconnected")
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None
        self._close_resources()

    def _close_resources(self) -> None:
        if self._process is not None:
            self._process.stdin.close()
        if self._conn is not None:
            self._conn.close()
        self._process = None
        self._conn = None

    def _fail_pending(self, message: str) -> None:
        if self._pending is not None and not self._pending.done():
            self._pending.set_exception(TesiraConnectionError(message))

    async def _drain_banner(self) -> None:
        """Discard the initial welcome banner text, if the device sends one."""
        assert self._process is not None
        try:
            while True:
                await asyncio.wait_for(self._process.stdout.readline(), timeout=BANNER_IDLE_TIMEOUT)
        except asyncio.TimeoutError:
            return
        except (asyncssh.Error, OSError):
            return

    async def _reader_loop(self) -> None:
        """Continuously read lines, routing "!" pushes to subscribers and
        "+OK"/"-ERR" lines to whichever command is currently awaiting one.
        """
        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                if line.startswith("!"):
                    self._dispatch_push(line)
                elif line.startswith("+OK") or line.startswith("-ERR"):
                    if self._pending is not None and not self._pending.done():
                        self._pending.set_result(line)
                # Anything else is unrecognized chatter; ignore it.
        except (asyncssh.Error, OSError):
            pass
        finally:
            self._fail_pending("connection closed by remote host")
            self._close_resources()
            self._reader_task = None
            if not self._closing:
                asyncio.create_task(self._auto_reconnect())

    def _dispatch_push(self, line: str) -> None:
        match = _PUBLISH_RE.match(line)
        if not match:
            _LOGGER.debug("Unrecognized push message: %s", line)
            return
        subscription = self._subscriptions.get(match.group("token"))
        if subscription is None:
            return
        subscription.callback(float(match.group("value")))

    async def _auto_reconnect(self) -> None:
        delay = RECONNECT_INITIAL_DELAY
        while not self._closing and not self.connected:
            await asyncio.sleep(delay)
            if self._closing:
                return
            try:
                await self.connect()
            except TesiraError as err:
                _LOGGER.warning(
                    "Reconnect to %s failed, retrying in %.0fs: %s", self._info.host, delay, err
                )
                delay = min(delay * 2, RECONNECT_MAX_DELAY)
                continue
            _LOGGER.info("Reconnected to Tesira at %s", self._info.host)
            return

    async def _send_raw(self, command: str) -> str:
        async with self._write_lock:
            if not self.connected:
                raise TesiraConnectionError("not connected")
            loop = asyncio.get_running_loop()
            self._pending = loop.create_future()
            try:
                self._process.stdin.write(command + "\n")
                await self._process.stdin.drain()
                return await asyncio.wait_for(self._pending, timeout=self._info.timeout)
            except asyncio.TimeoutError as err:
                raise TesiraConnectionError(
                    f"timed out waiting for a response to {command!r}"
                ) from err
            except (asyncssh.Error, OSError) as err:
                raise TesiraConnectionError(f"connection lost: {err}") from err
            finally:
                self._pending = None

    async def send_command(self, command: str) -> str:
        """Send a TTP command and return the body of a successful response."""
        response = await self._send_raw(command)
        if response.startswith("-ERR"):
            raise TesiraCommandError(command, response)
        return response[len("+OK") :].strip()

    async def async_test_session(self) -> None:
        """Send a harmless command to confirm the TTP shell is responsive."""
        await self.send_command("SESSION get aliases")

    async def recall_preset_by_name(self, name: str) -> None:
        await self.send_command(f'DEVICE recallPresetByName "{_escape_value(name)}"')

    async def _get_float(self, tag: str, attribute: str, channel: int) -> float:
        body = await self.send_command(f"{_quote_tag(tag)} get {attribute} {channel}")
        value = parse_float_value(body)
        if value is None:
            raise TesiraCommandError(
                f"{tag} get {attribute} {channel}", f"could not parse a numeric value from: {body}"
            )
        return value

    async def get_level(self, tag: str, channel: int) -> float:
        return await self._get_float(tag, "level", channel)

    async def set_level(self, tag: str, channel: int, value: float) -> None:
        await self.send_command(f"{_quote_tag(tag)} set level {channel} {value}")

    async def get_level_range(self, tag: str, channel: int) -> tuple[float, float]:
        """Return the (minLevel, maxLevel) dB bounds configured on the block."""
        min_level = await self._get_float(tag, "minLevel", channel)
        max_level = await self._get_float(tag, "maxLevel", channel)
        return min_level, max_level

    async def subscribe_level(
        self,
        tag: str,
        channel: int,
        token: str,
        callback: Callable[[float], None],
        throttle_ms: int = 250,
    ) -> None:
        """Subscribe to push updates for a level. The first push (the
        current value) arrives via `callback` almost immediately.

        Safe to call while disconnected: the subscription is recorded and
        will be armed automatically once connect() succeeds.
        """
        self._subscriptions[token] = _Subscription(
            tag=tag, channel=channel, throttle_ms=throttle_ms, callback=callback
        )
        if self.connected:
            await self._send_subscribe(token)

    async def _send_subscribe(self, token: str) -> None:
        subscription = self._subscriptions[token]
        await self.send_command(
            f"{_quote_tag(subscription.tag)} subscribe level {subscription.channel} "
            f"{token} {subscription.throttle_ms}"
        )

    async def unsubscribe_level(self, token: str) -> None:
        subscription = self._subscriptions.pop(token, None)
        if subscription is None or not self.connected:
            return
        try:
            await self.send_command(
                f"{_quote_tag(subscription.tag)} unsubscribe level {subscription.channel} {token}"
            )
        except TesiraError:
            pass  # best-effort; nothing to clean up if the session's already gone

    async def _resubscribe_all(self) -> None:
        for token in list(self._subscriptions):
            try:
                await self._send_subscribe(token)
            except TesiraError as err:
                _LOGGER.warning("Failed to re-subscribe %s: %s", token, err)
