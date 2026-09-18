"""Binary sensor platform for the Baby Tracker integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BabyTrackerConfigEntry
from .coordinator import BabyTrackerCoordinator
from .entity import BabyTrackerEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BabyTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Baby Tracker binary sensors from a config entry."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_entities() -> None:
        entities: list[BinarySensorEntity] = []
        for baby_id in coordinator.data.babies:
            if baby_id in known:
                continue
            known.add(baby_id)
            entities.append(BabyTrackerSleepingBinarySensor(coordinator, baby_id))
        if entities:
            async_add_entities(entities)

    _add_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_entities))


class BabyTrackerSleepingBinarySensor(BabyTrackerEntity, BinarySensorEntity):
    """Whether a sleep entry is running right now.

    The app writes a ``Sleep`` record with a start time and a duration, so a
    nap counts as in progress while ``time + duration`` is still ahead of us.
    """

    _attr_translation_key = "sleeping"
    _attr_icon = "mdi:sleep"

    def __init__(self, coordinator: BabyTrackerCoordinator, baby_id: str) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, "sleeping", baby_id)

    @property
    def is_on(self) -> bool | None:
        """Return whether the baby is asleep."""
        baby = self.baby
        return baby.sleeping if baby is not None else None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return when the current nap started and is due to end."""
        baby = self.baby
        if baby is None:
            return None
        record = baby.last.get("sleep")
        return {
            "started_at": record.time.isoformat()
            if record is not None and record.time
            else None,
            "ends_at": baby.sleep_ends_at.isoformat() if baby.sleep_ends_at else None,
            "sleep_today_hours": round(baby.today_sleep_seconds / 3600, 2),
        }
