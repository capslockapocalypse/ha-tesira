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
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

import asyncssh

_LOGGER = logging.getLogger(__name__)

BANNER_IDLE_TIMEOUT = 0.5

_VALUE_RE = re.compile(r'"value"\s*:\s*(-?\d+(?:\.\d+)?)')


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


class TesiraClient:
    """A serialized, reconnecting TTP-over-SSH command client."""

    def __init__(self, info: TesiraConnectionInfo) -> None:
        self._info = info
        self._conn: asyncssh.SSHClientConnection | None = None
        self._process: asyncssh.SSHClientProcess | None = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._process is not None and not self._process.stdin.is_closing()

    async def connect(self) -> None:
        """Open the SSH session and TTP shell channel."""
        if self.connected:
            return
        try:
            self._conn = await asyncssh.connect(
                self._info.host,
                port=self._info.port,
                username=self._info.username,
                password=self._info.password,
                known_hosts=None,
                login_timeout=self._info.timeout,
            )
            self._process = await self._conn.create_process(term_type="dumb", encoding="utf-8")
        except (OSError, asyncssh.Error) as err:
            await self._cleanup()
            raise TesiraConnectionError(f"could not connect to {self._info.host}: {err}") from err

        await self._drain_banner()

    async def disconnect(self) -> None:
        await self._cleanup()

    async def _cleanup(self) -> None:
        if self._process is not None:
            self._process.stdin.close()
        if self._conn is not None:
            self._conn.close()
            try:
                await self._conn.wait_closed()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
        self._process = None
        self._conn = None

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

    async def _send_raw(self, command: str) -> str:
        if not self.connected:
            raise TesiraConnectionError("not connected")

        async with self._lock:
            try:
                self._process.stdin.write(command + "\n")
                await self._process.stdin.drain()

                while True:
                    line = await asyncio.wait_for(
                        self._process.stdout.readline(), timeout=self._info.timeout
                    )
                    if not line:
                        raise TesiraConnectionError("connection closed by remote host")
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("+OK") or line.startswith("-ERR"):
                        return line
                    # Anything else is unsolicited/informational chatter; ignore it.
            except asyncio.TimeoutError as err:
                raise TesiraConnectionError(
                    f"timed out waiting for a response to {command!r}"
                ) from err
            except (asyncssh.Error, OSError) as err:
                await self._cleanup()
                raise TesiraConnectionError(f"connection lost: {err}") from err

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
