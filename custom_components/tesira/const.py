"""Constants for the Biamp Tesira integration."""
from __future__ import annotations

DOMAIN = "tesira"

CONF_PRESETS = "presets"
CONF_PRESET_NAME = "name"  # options-flow form field key

CONF_LEVELS = "levels"
CONF_LEVEL_TAG = "tag"  # options-flow form field key: the Level Control block's Instance Tag
CONF_LEVEL_CHANNEL = "channel"  # options-flow form field key

DEFAULT_PORT = 22
DEFAULT_TIMEOUT = 10  # seconds to wait for a single command response
DEFAULT_LEVEL_POLL_INTERVAL = 10  # seconds between level/mute polls
