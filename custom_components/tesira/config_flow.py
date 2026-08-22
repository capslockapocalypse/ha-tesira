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
    CONF_LEVEL_CHANNEL,
    CONF_LEVEL_TAG,
    CONF_LEVELS,
    CONF_PRESET_NAME,
    CONF_PRESETS,
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

ADD_PRESET_SCHEMA = vol.Schema({vol.Required(CONF_PRESET_NAME): str})

ADD_LEVEL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LEVEL_TAG): str,
        vol.Optional(CONF_LEVEL_CHANNEL, default=1): vol.Coerce(int),
    }
)


def _level_option_key(level: dict[str, Any]) -> str:
    return f"{level[CONF_LEVEL_TAG]}:{level[CONF_LEVEL_CHANNEL]}"


class _ConfigStepsMixin:
    """Add/remove steps for presets and levels, shared by both flows.

    Requires the including flow to maintain ``self._presets: list[str]``
    and ``self._levels: list[dict]``, to implement ``async_step_finish``,
    and to provide ``self._connection_info() -> TesiraConnectionInfo`` so a
    newly-added level block can be validated against the live device.
    """

    _presets: list[str]
    _levels: list[dict[str, Any]]

    def _connection_info(self) -> TesiraConnectionInfo:
        raise NotImplementedError

    async def async_step_menu(self, user_input: dict[str, Any] | None = None):
        return self.async_show_menu(  # type: ignore[attr-defined]
            step_id="menu",
            menu_options=[
                "add_preset",
                "remove_preset",
                "add_level",
                "remove_level",
                "finish",
            ],
        )

    async def async_step_add_preset(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_PRESET_NAME].strip()
            if not name:
                errors["base"] = "name_required"
            elif name in self._presets:
                errors["base"] = "already_exists"
            else:
                self._presets.append(name)
                return await self.async_step_menu()

        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="add_preset", data_schema=ADD_PRESET_SCHEMA, errors=errors
        )

    async def async_step_remove_preset(self, user_input: dict[str, Any] | None = None):
        if not self._presets:
            return await self.async_step_menu()

        if user_input is not None:
            to_remove = set(user_input["presets"])
            self._presets = [name for name in self._presets if name not in to_remove]
            return await self.async_step_menu()

        options = {name: name for name in self._presets}
        schema = vol.Schema({vol.Required("presets", default=[]): cv.multi_select(options)})
        return self.async_show_form(step_id="remove_preset", data_schema=schema)  # type: ignore[attr-defined]

    async def async_step_add_level(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            tag = user_input[CONF_LEVEL_TAG].strip()
            channel = user_input[CONF_LEVEL_CHANNEL]
            new_level = {CONF_LEVEL_TAG: tag, CONF_LEVEL_CHANNEL: channel}

            if not tag:
                errors["base"] = "tag_required"
            elif any(_level_option_key(lv) == _level_option_key(new_level) for lv in self._levels):
                errors["base"] = "level_already_exists"
            else:
                client = TesiraClient(self._connection_info())
                try:
                    await client.connect()
                    await client.get_level(tag, channel)
                except TesiraError:
                    errors["base"] = "level_not_found"
                else:
                    self._levels.append(new_level)
                    return await self.async_step_menu()
                finally:
                    await client.disconnect()

        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="add_level", data_schema=ADD_LEVEL_SCHEMA, errors=errors
        )

    async def async_step_remove_level(self, user_input: dict[str, Any] | None = None):
        if not self._levels:
            return await self.async_step_menu()

        if user_input is not None:
            to_remove = set(user_input["levels"])
            self._levels = [lv for lv in self._levels if _level_option_key(lv) not in to_remove]
            return await self.async_step_menu()

        options = {
            _level_option_key(lv): f"{lv[CONF_LEVEL_TAG]} (channel {lv[CONF_LEVEL_CHANNEL]})"
            for lv in self._levels
        }
        schema = vol.Schema({vol.Required("levels", default=[]): cv.multi_select(options)})
        return self.async_show_form(step_id="remove_level", data_schema=schema)  # type: ignore[attr-defined]


class TesiraConfigFlow(_ConfigStepsMixin, ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Biamp Tesira."""

    VERSION = 1

    def __init__(self) -> None:
        self._connection_data: dict[str, Any] = {}
        self._presets: list[str] = []
        self._levels: list[dict[str, Any]] = []

    def _connection_info(self) -> TesiraConnectionInfo:
        return TesiraConnectionInfo(
            host=self._connection_data[CONF_HOST],
            port=self._connection_data[CONF_PORT],
            username=self._connection_data[CONF_USERNAME],
            password=self._connection_data[CONF_PASSWORD],
            timeout=DEFAULT_TIMEOUT,
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            client = TesiraClient(
                TesiraConnectionInfo(
                    host=user_input[CONF_HOST],
                    port=user_input[CONF_PORT],
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                    timeout=DEFAULT_TIMEOUT,
                )
            )
            try:
                await client.connect()
                await client.async_test_session()
            except TesiraError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}")
                self._abort_if_unique_id_configured()
                self._connection_data = user_input
                return await self.async_step_menu()
            finally:
                await client.disconnect()

        return self.async_show_form(step_id="user", data_schema=USER_SCHEMA, errors=errors)

    async def async_step_finish(self, user_input: dict[str, Any] | None = None):
        return self.async_create_entry(
            title=f"Tesira ({self._connection_data[CONF_HOST]})",
            data=self._connection_data,
            options={CONF_PRESETS: self._presets, CONF_LEVELS: self._levels},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> TesiraOptionsFlow:
        return TesiraOptionsFlow(config_entry)


class TesiraOptionsFlow(_ConfigStepsMixin, OptionsFlow):
    """Manage presets and levels exposed as entities, after setup."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry_data: dict[str, Any] = dict(config_entry.data)
        self._presets: list[str] = list(config_entry.options.get(CONF_PRESETS, []))
        self._levels: list[dict[str, Any]] = list(config_entry.options.get(CONF_LEVELS, []))

    def _connection_info(self) -> TesiraConnectionInfo:
        return TesiraConnectionInfo(
            host=self._entry_data[CONF_HOST],
            port=self._entry_data[CONF_PORT],
            username=self._entry_data[CONF_USERNAME],
            password=self._entry_data[CONF_PASSWORD],
            timeout=DEFAULT_TIMEOUT,
        )

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        return await self.async_step_menu()

    async def async_step_finish(self, user_input: dict[str, Any] | None = None):
        return self.async_create_entry(
            title="", data={CONF_PRESETS: self._presets, CONF_LEVELS: self._levels}
        )
