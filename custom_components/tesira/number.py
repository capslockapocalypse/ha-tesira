"""Number platform for Biamp Tesira Level Control blocks."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .client import TesiraCommandError, TesiraConnectionError, TesiraError
from .const import CONF_LEVEL_CHANNEL, CONF_LEVEL_TAG, CONF_LEVELS, DOMAIN
from .coordinator import TesiraLevelCoordinator, level_key

_LOGGER = logging.getLogger(__name__)

DEFAULT_MIN_LEVEL = -100.0
DEFAULT_MAX_LEVEL = 12.0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    client = runtime_data.client
    coordinator = runtime_data.level_coordinator
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
            TesiraLevelNumber(coordinator, entry.entry_id, tag, channel, min_level, max_level)
        )

    async_add_entities(entities)


class TesiraLevelNumber(CoordinatorEntity[TesiraLevelCoordinator], NumberEntity):
    """A fader/level control, in dB, backed by a Tesira Level Control block."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "dB"
    _attr_mode = NumberMode.SLIDER
    _attr_native_step = 1.0

    def __init__(
        self,
        coordinator: TesiraLevelCoordinator,
        entry_id: str,
        tag: str,
        channel: int,
        min_level: float,
        max_level: float,
    ) -> None:
        super().__init__(coordinator)
        self._tag = tag
        self._channel = channel
        self._key = level_key(tag, channel)
        self._attr_name = tag if channel == 1 else f"{tag} channel {channel}"
        self._attr_unique_id = f"{entry_id}_level_{slugify(tag)}_{channel}"
        self._attr_native_min_value = min_level
        self._attr_native_max_value = max_level
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Biamp Tesira",
            manufacturer="Biamp",
            model="Tesira",
        )

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get(self._key)

    async def async_set_native_value(self, value: float) -> None:
        client = self.coordinator.client
        try:
            try:
                await client.set_level(self._tag, self._channel, value)
            except TesiraConnectionError:
                await client.connect()
                await client.set_level(self._tag, self._channel, value)
        except TesiraCommandError as err:
            raise HomeAssistantError(f"Tesira rejected the level change: {err}") from err
        except TesiraConnectionError as err:
            raise HomeAssistantError(f"Could not reach the Tesira: {err}") from err

        await self.coordinator.async_request_refresh()
