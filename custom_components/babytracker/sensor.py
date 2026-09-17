"""Sensor platform for the Baby Tracker integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BabyTrackerConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BabyTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Baby Tracker sensors from a config entry."""
    # TODO Create the sensors (last nursing/bottle/diaper/sleep, daily counts,
    # last volume, weight/length/head, temperature) from entry.runtime_data.
    entities: list[SensorEntity] = []
    async_add_entities(entities)
