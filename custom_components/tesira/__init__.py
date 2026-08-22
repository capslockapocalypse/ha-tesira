"""The Biamp Tesira integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .client import TesiraClient, TesiraConnectionInfo, TesiraError
from .const import CONF_MANUAL_PRESETS, DEFAULT_TIMEOUT, DOMAIN
from .coordinator import TesiraCoordinator

PLATFORMS: list[Platform] = [Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    info = TesiraConnectionInfo(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        timeout=DEFAULT_TIMEOUT,
    )
    client = TesiraClient(info)

    try:
        await client.connect()
    except TesiraError as err:
        raise ConfigEntryNotReady(str(err)) from err

    manual_presets = entry.options.get(CONF_MANUAL_PRESETS, [])
    coordinator = TesiraCoordinator(hass, client, manual_presets)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: TesiraCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.disconnect()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options (e.g. manual presets) change."""
    await hass.config_entries.async_reload(entry.entry_id)
