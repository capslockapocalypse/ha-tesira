"""Button platform for Biamp Tesira presets."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import TesiraCommandError, TesiraConnectionError
from .const import DOMAIN
from .coordinator import TesiraCoordinator, TesiraPreset


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: TesiraCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_keys: set[str] = set()

    @callback
    def _add_new_entities() -> None:
        new_entities = [
            TesiraPresetButton(coordinator, entry.entry_id, key)
            for key in coordinator.data
            if key not in known_keys
        ]
        known_keys.update(entity.preset_key for entity in new_entities)
        if new_entities:
            async_add_entities(new_entities)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


class TesiraPresetButton(CoordinatorEntity[TesiraCoordinator], ButtonEntity):
    """A push button that recalls one Tesira preset."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TesiraCoordinator, entry_id: str, preset_key: str) -> None:
        super().__init__(coordinator)
        self.preset_key = preset_key
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{preset_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Biamp Tesira",
            manufacturer="Biamp",
            model="Tesira",
        )

    @property
    def _preset(self) -> TesiraPreset | None:
        return self.coordinator.data.get(self.preset_key)

    @property
    def available(self) -> bool:
        return super().available and self._preset is not None

    @property
    def name(self) -> str | None:
        preset = self._preset
        return preset.name if preset else self.preset_key

    async def async_press(self) -> None:
        preset = self._preset
        if preset is None:
            raise HomeAssistantError(f"Preset '{self.preset_key}' is no longer known")

        client = self.coordinator.client
        try:
            try:
                await self._recall(preset)
            except TesiraConnectionError:
                # The persistent session may have dropped between polls; reconnect once.
                await client.connect()
                await self._recall(preset)
        except TesiraCommandError as err:
            raise HomeAssistantError(f"Tesira rejected the preset recall: {err}") from err

    async def _recall(self, preset: TesiraPreset) -> None:
        client = self.coordinator.client
        if preset.preset_id is not None:
            await client.recall_preset(preset.preset_id)
        else:
            await client.recall_preset_by_name(preset.name)
