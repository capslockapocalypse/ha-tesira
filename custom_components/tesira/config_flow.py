"""Config flow for the Biamp Tesira integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .client import TesiraClient, TesiraConnectionInfo, TesiraError
from .const import (
    CONF_MANUAL_PRESETS,
    CONF_PRESET_ID,
    CONF_PRESET_NAME,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DOMAIN,
)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
        vol.Required(CONF_USERNAME, default="default"): str,
        vol.Required(CONF_PASSWORD, default="default"): str,
    }
)

ADD_PRESET_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PRESET_NAME): str,
        vol.Optional(CONF_PRESET_ID): vol.Coerce(int),
    }
)


class TesiraConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Biamp Tesira."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            info = TesiraConnectionInfo(
                host=user_input[CONF_HOST],
                port=user_input[CONF_PORT],
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                timeout=DEFAULT_TIMEOUT,
            )
            client = TesiraClient(info)
            try:
                await client.connect()
                await client.get_aliases()
            except TesiraError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Tesira ({user_input[CONF_HOST]})", data=user_input
                )
            finally:
                await client.disconnect()

        return self.async_show_form(step_id="user", data_schema=USER_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> TesiraOptionsFlow:
        return TesiraOptionsFlow(config_entry)


class TesiraOptionsFlow(OptionsFlow):
    """Manage manually-defined presets that aren't backed by a Preset Button block."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._manual_presets: list[dict[str, Any]] = list(
            config_entry.options.get(CONF_MANUAL_PRESETS, [])
        )

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        return await self.async_step_menu()

    async def async_step_menu(self, user_input: dict[str, Any] | None = None):
        return self.async_show_menu(
            step_id="menu", menu_options=["add_preset", "remove_preset", "finish"]
        )

    async def async_step_add_preset(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_PRESET_NAME].strip()
            if not name:
                errors["base"] = "name_required"
            else:
                preset: dict[str, Any] = {CONF_PRESET_NAME: name}
                if CONF_PRESET_ID in user_input:
                    preset[CONF_PRESET_ID] = user_input[CONF_PRESET_ID]
                self._manual_presets = [
                    p for p in self._manual_presets if p[CONF_PRESET_NAME] != name
                ] + [preset]
                return await self.async_step_menu()

        return self.async_show_form(
            step_id="add_preset", data_schema=ADD_PRESET_SCHEMA, errors=errors
        )

    async def async_step_remove_preset(self, user_input: dict[str, Any] | None = None):
        if not self._manual_presets:
            return await self.async_step_menu()

        if user_input is not None:
            to_remove = set(user_input["presets"])
            self._manual_presets = [
                p for p in self._manual_presets if p[CONF_PRESET_NAME] not in to_remove
            ]
            return await self.async_step_menu()

        options = {p[CONF_PRESET_NAME]: p[CONF_PRESET_NAME] for p in self._manual_presets}
        schema = vol.Schema({vol.Required("presets", default=[]): cv.multi_select(options)})
        return self.async_show_form(step_id="remove_preset", data_schema=schema)

    async def async_step_finish(self, user_input: dict[str, Any] | None = None):
        return self.async_create_entry(
            title="", data={CONF_MANUAL_PRESETS: self._manual_presets}
        )
