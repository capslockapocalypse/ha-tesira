"""Number platform for Biamp Tesira Level Control blocks.

Values are pushed via TTP's native subscribe mechanism, not polled: each
entity subscribes once when added and updates its state directly as
`!`-prefixed push messages arrive on the persistent SSH session.
"""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .client import TesiraClient, TesiraCommandError, TesiraConnectionError, TesiraError
from .const import (
    CONF_LEVEL_CHANNEL,
    CONF_LEVEL_TAG,
    CONF_LEVELS,
    DEFAULT_LEVEL_SUBSCRIBE_THROTTLE_MS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_MIN_LEVEL = -100.0
DEFAULT_MAX_LEVEL = 12.0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    client: TesiraClient = hass.data[DOMAIN][entry.entry_id]
    levels: list[dict] = entry.options.get(CONF_LEVELS, [])

    entities: list[TesiraLevelNumber] = []
    for level in levels:
        tag = level[CONF_LEVEL_TAG]
        channel = level[CONF_LEVEL_CHANNEL]
        try:
            min_level, max_level = await client.get_level_range(tag, channel)
        except TesiraError as err:
            _LOGGER.warning(
                "Could not read level range for %s channel %s, using Tesira's absolute "
                "limits (%s to %s dB): %s",
                tag,
                channel,
                DEFAULT_MIN_LEVEL,
                DEFAULT_MAX_LEVEL,
                err,
            )
            min_level, max_level = DEFAULT_MIN_LEVEL, DEFAULT_MAX_LEVEL

        entities.append(
            TesiraLevelNumber(client, entry.entry_id, tag, channel, min_level, max_level)
        )

    async_add_entities(entities)


class TesiraLevelNumber(NumberEntity):
    """A fader/level control, in dB, backed by a Tesira Level Control block."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_native_unit_of_measurement = "dB"
    _attr_mode = NumberMode.SLIDER
    _attr_native_step = 1.0

    def __init__(
        self,
        client: TesiraClient,
        entry_id: str,
        tag: str,
        channel: int,
        min_level: float,
        max_level: float,
    ) -> None:
        self._client = client
        self._tag = tag
        self._channel = channel
        self._token = f"tesira_{slugify(tag)}_{channel}"
        self._attr_name = tag if channel == 1 else f"{tag} channel {channel}"
        self._attr_unique_id = f"{entry_id}_level_{slugify(tag)}_{channel}"
        self._attr_native_min_value = min_level
        self._attr_native_max_value = max_level
        self._attr_native_value: float | None = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Biamp Tesira",
            manufacturer="Biamp",
            model="Tesira",
        )

    @property
    def available(self) -> bool:
        # Not just self._client.connected: until the first push arrives we
        # don't actually know the current value yet.
        return self._client.connected and self._attr_native_value is not None

    async def async_added_to_hass(self) -> None:
        await self._client.subscribe_level(
            self._tag,
            self._channel,
            self._token,
            self._handle_push,
            throttle_ms=DEFAULT_LEVEL_SUBSCRIBE_THROTTLE_MS,
        )

    async def async_will_remove_from_hass(self) -> None:
        await self._client.unsubscribe_level(self._token)

    @callback
    def _handle_push(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        try:
            try:
                await self._client.set_level(self._tag, self._channel, value)
            except TesiraConnectionError:
                # The persistent session may have dropped since the last update.
                await self._client.connect()
                await self._client.set_level(self._tag, self._channel, value)
        except TesiraCommandError as err:
            raise HomeAssistantError(f"Tesira rejected the level change: {err}") from err
        except TesiraConnectionError as err:
            raise HomeAssistantError(f"Could not reach the Tesira: {err}") from err
        # No need to update state here: the subscription push confirms it shortly.
