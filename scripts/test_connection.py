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

    except TesiraError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    finally:
        await client.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
