"""Button platform for Biamp Tesira presets."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .client import TesiraClient, TesiraCommandError, TesiraConnectionError
from .const import CONF_PRESETS, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    client = hass.data[DOMAIN][entry.entry_id]
    presets: list[str] = entry.options.get(CONF_PRESETS, [])
    async_add_entities(
        TesiraPresetButton(client, entry.entry_id, name) for name in presets
    )


class TesiraPresetButton(ButtonEntity):
    """A push button that recalls one Tesira preset by name."""

    _attr_has_entity_name = True

    def __init__(self, client: TesiraClient, entry_id: str, preset_name: str) -> None:
        self._client = client
        self._preset_name = preset_name
        self._attr_name = preset_name
        self._attr_unique_id = f"{entry_id}_{slugify(preset_name)}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Biamp Tesira",
            manufacturer="Biamp",
            model="Tesira",
        )

    async def async_press(self) -> None:
        try:
            try:
                await self._client.recall_preset_by_name(self._preset_name)
            except TesiraConnectionError:
                # The persistent session may have dropped since the last press.
                await self._client.connect()
                await self._client.recall_preset_by_name(self._preset_name)
        except TesiraCommandError as err:
            raise HomeAssistantError(f"Tesira rejected the preset recall: {err}") from err
        except TesiraConnectionError as err:
            raise HomeAssistantError(f"Could not reach the Tesira: {err}") from err
