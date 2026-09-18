"""Data update coordinator for the Baby Tracker integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import BabyTrackerAuthError, BabyTrackerClient, BabyTrackerError, SyncState
from .const import (
    CONF_DEVICE_UUID,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_NAME,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .models import BabyTrackerData, build_data

_LOGGER = logging.getLogger(__name__)

#: Give the store a moment to coalesce writes; a busy account still only
#: rewrites the file once per sync burst.
SAVE_DELAY = 30


class BabyTrackerCoordinator(DataUpdateCoordinator[BabyTrackerData]):
    """Keep the local replay of the transaction log up to date.

    The first refresh downloads the account's whole history; afterwards the
    per-device cursors make each poll a handful of near-empty responses. The
    replayed records are persisted, so a Home Assistant restart resumes where
    it left off instead of re-downloading everything.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: BabyTrackerClient,
    ) -> None:
        """Initialise the coordinator for one config entry."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        #: Set once the account device is registered, for the babies' via_device.
        self.account_device_id: str | None = None
        self._store: Store[dict] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}"
        )

    async def _async_setup(self) -> None:
        """Restore the sync state before the first refresh."""
        stored = await self._store.async_load()
        state = SyncState.from_storage(stored, DEVICE_NAME)
        # The config entry owns the device UUID: the server keys our sync
        # cursor on it, so it must survive even a wiped store.
        state.device_uuid = self.config_entry.data[CONF_DEVICE_UUID]
        self.client.state = state
        if state.records:
            _LOGGER.debug("Restored %d record(s) from the store", len(state.records))

    async def _async_update_data(self) -> BabyTrackerData:
        """Fetch what changed and rebuild the dashboard view."""
        return await self._async_sync(full=False)

    async def async_refresh_full(self) -> None:
        """Drop the cursors and replay the account's history from scratch."""
        self.async_set_updated_data(await self._async_sync(full=True))

    async def _async_sync(self, *, full: bool) -> BabyTrackerData:
        """Run one sync and derive the coordinator payload from it."""
        try:
            applied = await self.client.async_sync(full=full)
        except BabyTrackerAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except BabyTrackerError as err:
            raise UpdateFailed(str(err)) from err

        if applied or full:
            self._store.async_delay_save(self.client.state.as_storage, SAVE_DELAY)

        return build_data(self.client.state, dt_util.now())

    async def async_save(self) -> None:
        """Flush the sync state to disk, e.g. when the entry is unloaded."""
        await self._store.async_save(self.client.state.as_storage())

    async def async_remove_store(self) -> None:
        """Delete the persisted sync state when the entry goes away."""
        await self._store.async_remove()
