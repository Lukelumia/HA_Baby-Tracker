"""Binary sensor platform for the Baby Tracker integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BabyTrackerConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BabyTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Baby Tracker binary sensors from a config entry."""
    # TODO Create the binary sensors (e.g. "sleeping now" per baby) from
    # entry.runtime_data.
    entities: list[BinarySensorEntity] = []
    async_add_entities(entities)
