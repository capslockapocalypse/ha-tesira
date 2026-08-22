#!/usr/bin/env python3
"""Stand-alone smoke test against a real Tesira, outside of Home Assistant.

Connects over SSH and confirms the TTP shell responds. Pass --recall
"<preset name>" to also call DEVICE recallPresetByName with it.

Usage:
    TESIRA_HOST=10.0.0.5 TESIRA_USERNAME=default TESIRA_PASSWORD=default \\
        .venv/bin/python scripts/test_connection.py

    ... --recall "Morning Announcement"
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import sys
import time
import types
from pathlib import Path

# client.py uses a relative import ("from .const import ...") so it must be
# loaded as part of a package. custom_components/tesira/__init__.py can't be
# that package here since it imports Home Assistant, which this stand-alone
# script has no need for - so build a synthetic one instead.
_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "tesira"
_PKG_NAME = "tesira_standalone"

_pkg = types.ModuleType(_PKG_NAME)
_pkg.__path__ = [str(_PKG_DIR)]
sys.modules[_PKG_NAME] = _pkg

for _module_name in ("const", "client"):
    _spec = importlib.util.spec_from_file_location(
        f"{_PKG_NAME}.{_module_name}", _PKG_DIR / f"{_module_name}.py"
    )
    _module = importlib.util.module_from_spec(_spec)
    _module.__package__ = _PKG_NAME
    sys.modules[_spec.name] = _module
    _spec.loader.exec_module(_module)

from tesira_standalone.client import TesiraClient, TesiraConnectionInfo, TesiraError  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("TESIRA_HOST"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("TESIRA_PORT", "22")))
    parser.add_argument("--username", default=os.environ.get("TESIRA_USERNAME", "default"))
    parser.add_argument("--password", default=os.environ.get("TESIRA_PASSWORD", "default"))
    parser.add_argument("--recall", help="Preset name to recall after connecting")
    parser.add_argument(
        "--get-level",
        action="append",
        default=[],
        metavar="TAG[:CHANNEL]",
        help="Read a Level Control block's value/min/max (repeatable)",
    )
    parser.add_argument(
        "--subscribe",
        metavar="TAG[:CHANNEL]",
        help="Subscribe to a level and print push updates for --subscribe-seconds",
    )
    parser.add_argument(
        "--subscribe-seconds", type=float, default=20.0, help="How long to listen for pushes"
    )
    parser.add_argument(
        "--set-level",
        metavar="TAG[:CHANNEL]=VALUE",
        help="Set a Level Control block's value, e.g. ProgramLevel=-20 or Zone2:2=-6",
    )
    args = parser.parse_args()

    if not args.host:
        parser.error("--host or TESIRA_HOST is required")

    client = TesiraClient(
        TesiraConnectionInfo(
            host=args.host, port=args.port, username=args.username, password=args.password
        )
    )

    try:
        print(f"Connecting to {args.host}:{args.port} as {args.username!r} ...")
        await client.connect()
        print("Connected.")

        print("Testing the TTP session (SESSION get aliases) ...")
        await client.async_test_session()
        print("Session is responsive.")

        if args.recall:
            print(f"\nRecalling preset {args.recall!r} ...")
            await client.recall_preset_by_name(args.recall)
            print("Recalled.")

        for spec in args.get_level:
            tag, _, channel_str = spec.partition(":")
            channel = int(channel_str) if channel_str else 1
            try:
                value = await client.get_level(tag, channel)
                min_level, max_level = await client.get_level_range(tag, channel)
                print(f"\n{tag} channel {channel}: {value} dB (range {min_level} to {max_level} dB)")
            except TesiraError as level_err:
                print(f"\n{tag} channel {channel}: ERROR: {level_err}")

        if args.set_level:
            spec, _, value_str = args.set_level.partition("=")
            tag, _, channel_str = spec.partition(":")
            channel = int(channel_str) if channel_str else 1
            value = float(value_str)
            print(f"\nSetting {tag} channel {channel} to {value} dB ...")
            await client.set_level(tag, channel, value)
            print("Set.")

        if args.subscribe:
            tag, _, channel_str = args.subscribe.partition(":")
            channel = int(channel_str) if channel_str else 1
            print(f"\nSubscribing to {tag} channel {channel} for {args.subscribe_seconds}s ...")

            def _on_push(value: float, _tag: str = tag) -> None:
                print(f"  [{time.strftime('%H:%M:%S')}] push: {_tag} = {value} dB")

            token = "test_connection_script"
            await client.subscribe_level(tag, channel, token, _on_push)
            await asyncio.sleep(args.subscribe_seconds)
            await client.unsubscribe_level(token)
            print("Unsubscribed.")

    except TesiraError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    finally:
        await client.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
