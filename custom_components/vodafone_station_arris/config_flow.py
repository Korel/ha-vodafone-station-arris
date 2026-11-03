"""Config flow: validates by doing one full login/read/logout cycle."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME

from .api import (
    ArrisStationClient,
    CannotConnect,
    InvalidAuth,
    NotArrisDevice,
    RouterData,
    SessionLost,
    WebUiBusy,
)
from .const import DEFAULT_HOST, DEFAULT_USERNAME, DOMAIN, LOGGER
from .session import standalone_session

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


async def _validate(data: Mapping[str, Any]) -> tuple[RouterData | None, dict[str, str]]:
    session = standalone_session()
    client = ArrisStationClient(data[CONF_HOST], data[CONF_USERNAME], data[CONF_PASSWORD], session)
    try:
        return await client.fetch(), {}
    except (WebUiBusy, SessionLost):
        return None, {"base": "web_ui_busy"}
    except InvalidAuth as err:
        LOGGER.debug("Login rejected: %s", err)
        return None, {"base": "invalid_auth"}
    except NotArrisDevice:
        return None, {"base": "not_arris"}
    except CannotConnect as err:
        LOGGER.debug("Cannot connect: %s", err)
        return None, {"base": "cannot_connect"}
    finally:
        await session.close()


class ArrisConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match({CONF_HOST: user_input[CONF_HOST]})
            router, errors = await _validate(user_input)
            if router is not None:
                await self.async_set_unique_id(router.serial_number or user_input[CONF_HOST])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=f"Vodafone Station {router.model}", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            router, errors = await _validate(data)
            if router is not None:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={CONF_HOST: entry.data[CONF_HOST]},
            errors=errors,
        )
