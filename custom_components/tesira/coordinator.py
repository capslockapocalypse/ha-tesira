"""Polling coordinator for Tesira Level Control blocks."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import TesiraClient, TesiraError
from .const import CONF_LEVEL_CHANNEL, CONF_LEVEL_TAG, DEFAULT_LEVEL_POLL_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


def level_key(tag: str, channel: int) -> str:
    return f"{tag}:{channel}"


class TesiraLevelCoordinator(DataUpdateCoordinator[dict[str, float]]):
    """Polls every configured Level Control block's fader value."""

    def __init__(self, hass: HomeAssistant, client: TesiraClient, levels: list[dict]) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_levels",
            update_interval=timedelta(seconds=DEFAULT_LEVEL_POLL_INTERVAL),
        )
        self.client = client
        self.levels = levels

    async def _async_update_data(self) -> dict[str, float]:
        try:
            if not self.client.connected:
                await self.client.connect()

            data: dict[str, float] = {}
            for entry in self.levels:
                tag = entry[CONF_LEVEL_TAG]
                channel = entry[CONF_LEVEL_CHANNEL]
                data[level_key(tag, channel)] = await self.client.get_level(tag, channel)
            return data
        except TesiraError as err:
            raise UpdateFailed(str(err)) from err
