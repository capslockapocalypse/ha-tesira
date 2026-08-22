"""The Biamp Tesira integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .client import TesiraClient, TesiraConnectionInfo, TesiraError
from .const import DEFAULT_TIMEOUT, DOMAIN

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.NUMBER]


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
        await client.async_test_session()
    except TesiraError as err:
        await client.disconnect()
        raise ConfigEntryNotReady(str(err)) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = client
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        client: TesiraClient = hass.data[DOMAIN].pop(entry.entry_id)
        await client.disconnect()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options (presets/levels) change."""
    await hass.config_entries.async_reload(entry.entry_id)
