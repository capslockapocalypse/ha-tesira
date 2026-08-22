"""Constants for the Biamp Tesira integration."""
from __future__ import annotations

DOMAIN = "tesira"

CONF_MANUAL_PRESETS = "manual_presets"
CONF_PRESET_NAME = "name"
CONF_PRESET_ID = "preset_id"

DEFAULT_PORT = 22
DEFAULT_SCAN_INTERVAL = 300  # seconds between preset re-discovery polls
DEFAULT_TIMEOUT = 10  # seconds to wait for a single command response

# Instance tags that are never Preset Buttons and can be skipped during probing.
RESERVED_ALIASES = {"DEVICE", "SESSION"}
