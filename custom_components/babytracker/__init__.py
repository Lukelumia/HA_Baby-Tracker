"""The Baby Tracker integration.

Polls the Baby Tracker (Nighp) cloud sync API for your own account, replays the
transaction log locally and exposes the result as sensors.
"""

from __future__ import annotations

import uuid

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .api import BabyTrackerClient
from .const import (
    ACCOUNT_MODEL,
    CONF_DEVICE_UUID,
    CONFIGURATION_URL,
    DOMAIN,
    MANUFACTURER,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .coordinator import BabyTrackerCoordinator
from .services import async_setup_services

_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.IMAGE,
    Platform.SENSOR,
]

type BabyTrackerConfigEntry = ConfigEntry[BabyTrackerCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BabyTrackerConfigEntry) -> bool:
    """Set up Baby Tracker from a config entry."""
    if not entry.data.get(CONF_DEVICE_UUID):
        # Entries created before the client existed have no UUID yet. One is
        # generated here so the server can keep a sync cursor for us.
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_DEVICE_UUID: str(uuid.uuid4()).upper()},
        )

    # A session of our own: the API authenticates with a plain cookie, so the
    # cookie jar must not be shared with the rest of Home Assistant.
    session = async_create_clientsession(hass, auto_cleanup=False)
    entry.async_on_unload(session.close)

    client = BabyTrackerClient(
        session,
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
    )
    coordinator = BabyTrackerCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # The account is the hub every baby hangs off, so it has to exist in the
    # device registry before the platforms create their entities.
    account_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=MANUFACTURER,
        model=ACCOUNT_MODEL,
        name=entry.title,
        configuration_url=CONFIGURATION_URL,
    )
    coordinator.account_device_id = account_device.id

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BabyTrackerConfigEntry
) -> bool:
    """Unload a config entry, flushing the sync state first."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
    coordinator = getattr(entry, "runtime_data", None)
    if unloaded and coordinator is not None:
        await coordinator.async_save()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop the stored sync state when the entry is deleted."""
    store: Store[dict] = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}")
    await store.async_remove()
