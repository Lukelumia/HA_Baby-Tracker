"""Image platform for the Baby Tracker integration."""

from __future__ import annotations

import logging

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import BabyTrackerConfigEntry
from .api import BabyTrackerError
from .coordinator import BabyTrackerCoordinator
from .entity import BabyTrackerEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BabyTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up an image entity for every baby that has a photo."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_entities() -> None:
        entities: list[ImageEntity] = []
        for baby_id, baby in coordinator.data.babies.items():
            if baby_id in known or not baby.picture_id:
                continue
            known.add(baby_id)
            entities.append(BabyTrackerPhoto(coordinator, baby_id))
        if entities:
            async_add_entities(entities)

    _add_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_entities))


class BabyTrackerPhoto(BabyTrackerEntity, ImageEntity):
    """The baby's photo, as stored in the Baby Tracker account."""

    _attr_translation_key = "photo"
    _attr_content_type = "image/jpeg"

    def __init__(self, coordinator: BabyTrackerCoordinator, baby_id: str) -> None:
        """Initialise the image entity."""
        super().__init__(coordinator, "photo", baby_id)
        ImageEntity.__init__(self, coordinator.hass)
        baby = coordinator.data.babies.get(baby_id)
        self._picture_id = baby.picture_id if baby else None
        self._cached: bytes | None = None
        self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Drop the cached photo when the account points at a new one."""
        baby = self.baby
        picture_id = baby.picture_id if baby else None
        if picture_id != self._picture_id:
            self._picture_id = picture_id
            self._cached = None
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Return the photo, downloading it once and keeping it cached."""
        if self._cached is not None:
            return self._cached
        if not self._picture_id:
            return None
        try:
            self._cached = await self.coordinator.client.async_get_picture(
                self._picture_id
            )
        except BabyTrackerError as err:
            _LOGGER.debug("Could not download the photo: %s", err)
            return None
        return self._cached
