"""Data update coordinator for the Biamp Tesira integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import TesiraClient, TesiraError
from .const import CONF_PRESET_ID, CONF_PRESET_NAME, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TesiraPreset:
    """A preset exposed to Home Assistant, whether discovered or manual."""

    name: str
    preset_id: int | None
    source: str  # "auto" (Preset Button block) or "manual" (user configured)


class TesiraCoordinator(DataUpdateCoordinator[dict[str, TesiraPreset]]):
    """Polls the Tesira for its Preset Button blocks and merges manual presets."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: TesiraClient,
        manual_presets: list[dict],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self.manual_presets = manual_presets

    async def _async_update_data(self) -> dict[str, TesiraPreset]:
        try:
            if not self.client.connected:
                await self.client.connect()
            discovered = await self.client.discover_preset_buttons()
        except TesiraError as err:
            raise UpdateFailed(str(err)) from err

        presets: dict[str, TesiraPreset] = {
            tag.casefold(): TesiraPreset(name=tag, preset_id=preset_id, source="auto")
            for tag, preset_id in discovered.items()
        }

        for manual in self.manual_presets:
            name = manual[CONF_PRESET_NAME]
            presets[name.casefold()] = TesiraPreset(
                name=name,
                preset_id=manual.get(CONF_PRESET_ID),
                source="manual",
            )

        return presets
