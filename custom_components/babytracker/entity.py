"""Base entity for the Baby Tracker integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ACCOUNT_MODEL, BABY_MODEL, CONFIGURATION_URL, DOMAIN, MANUFACTURER
from .coordinator import BabyTrackerCoordinator
from .models import AccountStats, BabyStats


class BabyTrackerEntity(CoordinatorEntity[BabyTrackerCoordinator]):
    """An entity backed by the account's replayed transaction log.

    Entities either belong to a baby (its own device, linked to the account)
    or to the account itself, which is also the hub the babies hang off.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BabyTrackerCoordinator,
        key: str,
        baby_id: str | None = None,
    ) -> None:
        """Set the unique id and the device this entity belongs to."""
        super().__init__(coordinator)
        self._baby_id = baby_id
        entry = coordinator.config_entry

        if baby_id is None:
            self._attr_unique_id = f"{entry.entry_id}_{key}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, entry.entry_id)},
                manufacturer=MANUFACTURER,
                model=ACCOUNT_MODEL,
                name=entry.title,
                configuration_url=CONFIGURATION_URL,
            )
            return

        self._attr_unique_id = f"{entry.entry_id}_{baby_id}_{key}"
        baby = coordinator.data.babies.get(baby_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{baby_id}")},
            manufacturer=MANUFACTURER,
            model=BABY_MODEL,
            name=baby.name if baby else "Baby",
        )
        if coordinator.account_device_id is not None:
            self._attr_device_info["via_device_id"] = coordinator.account_device_id

    @property
    def baby(self) -> BabyStats | None:
        """The baby this entity reports on, if it is a per-baby entity."""
        if self._baby_id is None:
            return None
        return self.coordinator.data.babies.get(self._baby_id)

    @property
    def account(self) -> AccountStats:
        """The account-wide figures."""
        return self.coordinator.data.account

    @property
    def available(self) -> bool:
        """Whether the backing data is still there."""
        if not super().available:
            return False
        return self._baby_id is None or self._baby_id in self.coordinator.data.babies
