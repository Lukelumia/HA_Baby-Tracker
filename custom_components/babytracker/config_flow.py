"""Config flow for the Baby Tracker integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import BabyTrackerAuthError, BabyTrackerClient, BabyTrackerError, SyncState
from .const import CONF_DEVICE_UUID, DEVICE_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate that the credentials can log in.

    The login also registers this device UUID on the account, so the same UUID
    the config entry will store is used here — a throwaway one would leave a
    stray device behind on every attempt.
    """
    session = async_create_clientsession(hass, auto_cleanup=False)
    client = BabyTrackerClient(
        session,
        data[CONF_EMAIL],
        data[CONF_PASSWORD],
        SyncState(device_uuid=data[CONF_DEVICE_UUID], device_name=DEVICE_NAME),
    )
    try:
        await client.async_login()
    except BabyTrackerAuthError as err:
        raise InvalidAuth from err
    except BabyTrackerError as err:
        raise CannotConnect from err
    finally:
        await session.close()

    return {"title": data[CONF_EMAIL]}


class BabyTrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Baby Tracker."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_EMAIL].casefold())
            self._abort_if_unique_id_configured()
            data = {**user_input, CONF_DEVICE_UUID: str(uuid.uuid4()).upper()}
            try:
                info = await validate_input(self.hass, data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=data)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a password that the server no longer accepts."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the current password and check it before storing it."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**entry.data, **user_input}
            data.setdefault(CONF_DEVICE_UUID, str(uuid.uuid4()).upper())
            try:
                await validate_input(self.hass, data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={CONF_EMAIL: entry.data[CONF_EMAIL]},
            errors=errors,
        )


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""
