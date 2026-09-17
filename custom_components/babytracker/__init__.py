"""The Baby Tracker integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

_PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

# TODO Replace `object` with the API/coordinator object stored on the entry and
# update the annotations below.
type BabyTrackerConfigEntry = ConfigEntry[object]


async def async_setup_entry(hass: HomeAssistant, entry: BabyTrackerConfigEntry) -> bool:
    """Set up Baby Tracker from a config entry."""

    # TODO 1. Create the API client (POST /session with the stored credentials).
    # TODO 2. Validate the connection and authentication, raising
    #         ConfigEntryAuthFailed / ConfigEntryNotReady as appropriate.
    # TODO 3. Store the client (or its coordinator) for the platforms to use:
    # entry.runtime_data = BabyTrackerClient(...)

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BabyTrackerConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
