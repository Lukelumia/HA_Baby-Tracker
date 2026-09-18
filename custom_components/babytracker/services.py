"""Actions exposed by the Baby Tracker integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import ConfigEntrySelector

from .const import ATTR_CONFIG_ENTRY_ID, ATTR_FULL, DOMAIN, SERVICE_REFRESH

if TYPE_CHECKING:
    from . import BabyTrackerConfigEntry

SERVICE_REFRESH_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): ConfigEntrySelector(
            {"integration": DOMAIN}
        ),
        vol.Optional(ATTR_FULL, default=False): cv.boolean,
    }
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration-level actions."""

    async def async_refresh(call: ServiceCall) -> None:
        """Sync now, optionally replaying the whole history again."""
        entry_id: str = call.data[ATTR_CONFIG_ENTRY_ID]
        entry: BabyTrackerConfigEntry | None = call.hass.config_entries.async_get_entry(
            entry_id
        )
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_found",
                translation_placeholders={"target": entry_id},
            )
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_loaded",
                translation_placeholders={"target": entry.title},
            )

        coordinator = entry.runtime_data
        if call.data[ATTR_FULL]:
            await coordinator.async_refresh_full()
        else:
            await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, async_refresh, schema=SERVICE_REFRESH_SCHEMA
    )
