"""Minimal client for the Biamp Tesira Text Protocol (TTP) over SSH.

Protocol reference: Biamp Cornerstone "Tesira Text Protocol" manual (v4.2).

Key facts this client relies on:
  * SSH authentication (username/password) happens at the transport layer.
    Once the SSH session is open there is no separate TTP login step.
  * Commands are single ASCII lines terminated with a line feed.
  * Responses start with "+OK" (success, optionally followed by a
    "key":value payload) or "-ERR" (failure, followed by a reason).
  * There is no TTP command that lists all presets in a design. The only
    way to discover presets over TTP is via Preset Button blocks: each is
    a named Instance Tag whose "preset" attribute holds the preset ID it
    is wired to (`<tag> get preset 1` -> `+OK "value":<id>`). All
    Instance Tags in a design can be listed with `SESSION get aliases`.
    Recalling a preset is always done via the DEVICE service commands
    (`recallPreset` / `recallPresetByName`), never via the button tag.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

import asyncssh

from .const import RESERVED_ALIASES

_LOGGER = logging.getLogger(__name__)

_VALUE_RE = re.compile(r'"value"\s*:\s*(-?\d+(?:\.\d+)?|true|false|null|"(?:[^"\\]|\\.)*")')
_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_LIST_RE = re.compile(r'"list"\s*:\s*\[(.*?)\]')

BANNER_IDLE_TIMEOUT = 0.5


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


def _quote_tag(tag: str) -> str:
    """Quote an Instance Tag if it contains whitespace, per TTP syntax rules."""
    if re.search(r"\s", tag):
        return f'"{tag}"'
    return tag


def parse_value(body: str) -> str | None:
    """Extract the raw "value":X token from a response body, if present."""
    match = _VALUE_RE.search(body)
    return match.group(1) if match else None


def parse_int_value(body: str) -> int | None:
    raw = parse_value(body)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def parse_list(body: str) -> list[str]:
    """Extract the quoted string entries of a "list":[...] response body."""
    match = _LIST_RE.search(body)
    if not match:
        return []
    return _STRING_RE.findall(match.group(1))


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
            # A PTY is required: without one, the Tesira accepts the SSH
            # session and banner but silently drops the connection the
            # moment a command is written to stdin. Confirmed against a
            # live TesiraFORTE over SSH.
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

    async def get_aliases(self) -> list[str]:
        body = await self.send_command("SESSION get aliases")
        return parse_list(body)

    async def probe_preset_button(self, tag: str) -> int | None:
        """Return the preset ID a Preset Button Instance Tag is assigned to.

        Returns None if the tag isn't a Preset Button (or any other error
        occurs) so callers can safely probe every alias in a design.
        """
        try:
            body = await self.send_command(f"{_quote_tag(tag)} get preset 1")
        except TesiraCommandError:
            return None
        return parse_int_value(body)

    async def discover_preset_buttons(self) -> dict[str, int]:
        """Discover all Preset Button blocks by probing every Instance Tag.

        Returns a mapping of Instance Tag name -> assigned preset ID.
        """
        aliases = await self.get_aliases()
        discovered: dict[str, int] = {}
        for tag in aliases:
            if tag in RESERVED_ALIASES:
                continue
            preset_id = await self.probe_preset_button(tag)
            if preset_id is not None:
                discovered[tag] = preset_id
        return discovered

    async def recall_preset(self, preset_id: int) -> None:
        await self.send_command(f"DEVICE recallPreset {int(preset_id)}")

    async def recall_preset_by_name(self, name: str) -> None:
        await self.send_command(f'DEVICE recallPresetByName "{name}"')
