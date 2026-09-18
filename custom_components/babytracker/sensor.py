"""Sensor platform for the Baby Tracker integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import datetime as dt
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfLength,
    UnitOfMass,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from . import BabyTrackerConfigEntry
from .const import DIAPER_STATUSES
from .coordinator import BabyTrackerCoordinator
from .entity import BabyTrackerEntity
from .models import AccountStats, BabyStats

PARALLEL_UPDATES = 0


# --------------------------------------------------------------------------- #
# value helpers
# --------------------------------------------------------------------------- #


def _last_time(key: str) -> Callable[[BabyStats, dt.datetime], dt.datetime | None]:
    """Timestamp of the most recent event of a kind."""

    def value(baby: BabyStats, now: dt.datetime) -> dt.datetime | None:
        record = baby.last.get(key)
        return record.when if record is not None else None

    return value


def _last_attrs(key: str) -> Callable[[BabyStats], Mapping[str, Any] | None]:
    """Decoded fields of the most recent event of a kind."""

    def attrs(baby: BabyStats) -> Mapping[str, Any] | None:
        record = baby.last.get(key)
        if record is None:
            return None
        data: dict[str, Any] = {
            "record_type": record.record_type,
            "record_id": record.object_id,
        }
        if record.note:
            data["note"] = record.note
        data.update(
            {name: value for name, value in record.fields.items() if name != "pictures"}
        )
        return data

    return attrs


def _count(key: str) -> Callable[[BabyStats, dt.datetime], StateType]:
    """How many events of a kind happened today."""

    def value(baby: BabyStats, now: dt.datetime) -> StateType:
        return baby.today.get(key, 0)

    return value


def _last_field(
    key: str, name: str, scale: float = 1.0, digits: int = 1
) -> Callable[[BabyStats, dt.datetime], StateType]:
    """A numeric field of the most recent event of a kind."""

    def value(baby: BabyStats, now: dt.datetime) -> StateType:
        record = baby.last.get(key)
        if record is None:
            return None
        raw = record.fields.get(name)
        if raw is None:
            return None
        return round(float(raw) * scale, digits)

    return value


def _measurement(
    name: str, digits: int = 2
) -> Callable[[BabyStats, dt.datetime], StateType]:
    """The latest growth or temperature reading."""

    def value(baby: BabyStats, now: dt.datetime) -> StateType:
        entry = baby.measurements.get(name)
        return round(entry.value, digits) if entry is not None else None

    return value


def _measurement_attrs(name: str) -> Callable[[BabyStats], Mapping[str, Any] | None]:
    """When the latest reading was taken."""

    def attrs(baby: BabyStats) -> Mapping[str, Any] | None:
        entry = baby.measurements.get(name)
        if entry is None or entry.when is None:
            return None
        return {"measured_at": entry.when.isoformat()}

    return attrs


def _always(_: Any) -> bool:
    """Create this entity whatever the account contains."""
    return True


def _has(key: str) -> Callable[[BabyStats | AccountStats], bool]:
    """Create this entity only once the account has such a record."""

    def exists(stats: BabyStats | AccountStats) -> bool:
        return key in stats.total

    return exists


# --------------------------------------------------------------------------- #
# descriptions
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class BabyTrackerSensorEntityDescription(SensorEntityDescription):
    """Describes a Baby Tracker sensor belonging to a baby."""

    value_fn: Callable[[BabyStats, dt.datetime], StateType | dt.datetime]
    attrs_fn: Callable[[BabyStats], Mapping[str, Any] | None] | None = None
    exists_fn: Callable[[BabyStats], bool] = _always


@dataclass(frozen=True, kw_only=True)
class BabyTrackerAccountSensorEntityDescription(SensorEntityDescription):
    """Describes a Baby Tracker sensor belonging to the account."""

    value_fn: Callable[[AccountStats, dt.datetime], StateType | dt.datetime]
    attrs_fn: Callable[[AccountStats], Mapping[str, Any] | None] | None = None
    exists_fn: Callable[[AccountStats], bool] = _always


#: (logical key, icon, always create) for the "last <event>" timestamp sensors.
_EVENTS: tuple[tuple[str, str, bool], ...] = (
    ("feed", "mdi:food-apple", True),
    ("nursing", "mdi:mother-nurse", False),
    ("bottle", "mdi:baby-bottle", True),
    ("formula", "mdi:baby-bottle-outline", False),
    ("pumped", "mdi:cup-outline", False),
    ("other_feed", "mdi:silverware-fork-knife", False),
    ("diaper", "mdi:human-baby-changing-table", True),
    ("wet_diaper", "mdi:water", False),
    ("dirty_diaper", "mdi:emoticon-poop", False),
    ("sleep", "mdi:sleep", True),
    ("bath", "mdi:shower-head", False),
    ("growth", "mdi:chart-line", False),
    ("temperature", "mdi:thermometer", False),
    ("medication", "mdi:pill", False),
    ("milestone", "mdi:star-outline", False),
    ("vaccine", "mdi:needle", False),
    ("journal", "mdi:notebook-outline", False),
    ("joy", "mdi:emoticon-happy-outline", False),
    ("other_activity", "mdi:dots-horizontal", False),
)

#: Logical keys that also get a "today" counter.
_COUNTS: tuple[tuple[str, str, bool], ...] = (
    ("feed", "mdi:food-apple", True),
    ("nursing", "mdi:mother-nurse", False),
    ("bottle", "mdi:baby-bottle", True),
    ("diaper", "mdi:human-baby-changing-table", True),
    ("wet_diaper", "mdi:water", False),
    ("dirty_diaper", "mdi:emoticon-poop", False),
    ("sleep", "mdi:sleep", True),
    ("bath", "mdi:shower-head", False),
    ("medication", "mdi:pill", False),
)

BABY_SENSORS: tuple[BabyTrackerSensorEntityDescription, ...] = (
    *(
        BabyTrackerSensorEntityDescription(
            key=f"last_{key}",
            translation_key=f"last_{key}",
            icon=icon,
            device_class=SensorDeviceClass.TIMESTAMP,
            value_fn=_last_time(key),
            attrs_fn=_last_attrs(key),
            exists_fn=_always if always else _has(key),
        )
        for key, icon, always in _EVENTS
    ),
    *(
        BabyTrackerSensorEntityDescription(
            key=f"{key}_today",
            translation_key=f"{key}_today",
            icon=icon,
            state_class=SensorStateClass.TOTAL_INCREASING,
            value_fn=_count(key),
            exists_fn=_always if always else _has(key),
        )
        for key, icon, always in _COUNTS
    ),
    BabyTrackerSensorEntityDescription(
        key="last_bottle_amount",
        translation_key="last_bottle_amount",
        icon="mdi:baby-bottle",
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_last_field("bottle", "amount_ml", digits=1),
        exists_fn=_has("bottle"),
    ),
    BabyTrackerSensorEntityDescription(
        key="bottle_volume_today",
        translation_key="bottle_volume_today",
        icon="mdi:baby-bottle-outline",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=lambda baby, now: baby.today_bottle_ml,
        exists_fn=_has("bottle"),
    ),
    BabyTrackerSensorEntityDescription(
        key="last_nursing_duration",
        translation_key="last_nursing_duration",
        icon="mdi:timer-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_last_field("nursing", "duration", scale=1 / 60, digits=1),
        exists_fn=_has("nursing"),
    ),
    BabyTrackerSensorEntityDescription(
        key="nursing_duration_today",
        translation_key="nursing_duration_today",
        icon="mdi:timer-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=lambda baby, now: round(baby.today_nursing_seconds / 60, 1),
        exists_fn=_has("nursing"),
    ),
    BabyTrackerSensorEntityDescription(
        key="last_sleep_duration",
        translation_key="last_sleep_duration",
        icon="mdi:timer-sand",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_last_field("sleep", "duration", scale=1 / 60, digits=1),
        exists_fn=_has("sleep"),
    ),
    BabyTrackerSensorEntityDescription(
        key="sleep_duration_today",
        translation_key="sleep_duration_today",
        icon="mdi:sleep",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda baby, now: round(baby.today_sleep_seconds / 3600, 2),
    ),
    BabyTrackerSensorEntityDescription(
        key="last_diaper_status",
        translation_key="last_diaper_status",
        icon="mdi:human-baby-changing-table",
        device_class=SensorDeviceClass.ENUM,
        options=[status.lower() for status in DIAPER_STATUSES],
        value_fn=lambda baby, now: (
            (
                (record := baby.last.get("diaper"))
                and str(record.fields.get("status") or "").lower()
            )
            or None
        ),
        exists_fn=_has("diaper"),
    ),
    BabyTrackerSensorEntityDescription(
        key="weight",
        translation_key="weight",
        icon="mdi:scale-bathroom",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=_measurement("weight_kg", digits=3),
        attrs_fn=_measurement_attrs("weight_kg"),
        exists_fn=_has("growth"),
    ),
    BabyTrackerSensorEntityDescription(
        key="length",
        translation_key="length",
        icon="mdi:human-male-height",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_measurement("length_cm"),
        attrs_fn=_measurement_attrs("length_cm"),
        exists_fn=_has("growth"),
    ),
    BabyTrackerSensorEntityDescription(
        key="head_circumference",
        translation_key="head_circumference",
        icon="mdi:head-outline",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_measurement("head_cm"),
        attrs_fn=_measurement_attrs("head_cm"),
        exists_fn=_has("growth"),
    ),
    BabyTrackerSensorEntityDescription(
        key="temperature",
        translation_key="body_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_measurement("temperature_c"),
        attrs_fn=_measurement_attrs("temperature_c"),
        exists_fn=_has("temperature"),
    ),
    BabyTrackerSensorEntityDescription(
        key="age",
        translation_key="age",
        icon="mdi:cake-variant",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda baby, now: baby.age_days(now),
        attrs_fn=lambda baby: (
            {"date_of_birth": baby.dob.isoformat()} if baby.dob else None
        ),
    ),
)

ACCOUNT_SENSORS: tuple[BabyTrackerAccountSensorEntityDescription, ...] = (
    BabyTrackerAccountSensorEntityDescription(
        key="last_pump",
        translation_key="last_pump",
        icon="mdi:pump",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda account, now: (
            record.when if (record := account.last.get("pump")) else None
        ),
        attrs_fn=lambda account: (
            dict(record.fields) if (record := account.last.get("pump")) else None
        ),
        exists_fn=_has("pump"),
    ),
    BabyTrackerAccountSensorEntityDescription(
        key="pump_today",
        translation_key="pump_today",
        icon="mdi:pump",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda account, now: account.today.get("pump", 0),
        exists_fn=_has("pump"),
    ),
    BabyTrackerAccountSensorEntityDescription(
        key="pump_volume_today",
        translation_key="pump_volume_today",
        icon="mdi:cup-water",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=lambda account, now: account.today_pump_ml,
        exists_fn=_has("pump"),
    ),
    BabyTrackerAccountSensorEntityDescription(
        key="last_sync",
        translation_key="last_sync",
        icon="mdi:cloud-sync-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda account, now: account.synced_at,
    ),
    BabyTrackerAccountSensorEntityDescription(
        key="records",
        translation_key="records",
        icon="mdi:database-outline",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda account, now: account.record_count,
        attrs_fn=lambda account: {
            "account_id": account.account_id,
            "devices": [
                {"name": device.get("name"), "uuid": device.get("uuid")}
                for device in account.devices
            ],
        },
    ),
    BabyTrackerAccountSensorEntityDescription(
        key="sync_devices",
        translation_key="sync_devices",
        icon="mdi:devices",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda account, now: len(account.devices),
    ),
)


# --------------------------------------------------------------------------- #
# platform
# --------------------------------------------------------------------------- #


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BabyTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Baby Tracker sensors from a config entry.

    Entities are created for the kinds of record the account actually holds,
    and the listener keeps watching: log a first bath months from now and its
    sensors appear on the next refresh.
    """
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_entities() -> None:
        entities: list[SensorEntity] = []
        data = coordinator.data

        for baby_id, baby in data.babies.items():
            for description in BABY_SENSORS:
                unique = f"{baby_id}.{description.key}"
                if unique in known or not description.exists_fn(baby):
                    continue
                known.add(unique)
                entities.append(BabyTrackerSensor(coordinator, description, baby_id))

        for account_description in ACCOUNT_SENSORS:
            unique = f"account.{account_description.key}"
            if unique in known or not account_description.exists_fn(data.account):
                continue
            known.add(unique)
            entities.append(BabyTrackerAccountSensor(coordinator, account_description))

        if entities:
            async_add_entities(entities)

    _add_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_entities))


class BabyTrackerSensor(BabyTrackerEntity, SensorEntity):
    """A sensor reporting on one baby."""

    entity_description: BabyTrackerSensorEntityDescription

    def __init__(
        self,
        coordinator: BabyTrackerCoordinator,
        description: BabyTrackerSensorEntityDescription,
        baby_id: str,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key, baby_id)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | dt.datetime:
        """Return the current value."""
        baby = self.baby
        if baby is None:
            return None
        return self.entity_description.value_fn(baby, dt_util.now())

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return the decoded record behind this value."""
        baby = self.baby
        if baby is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(baby)


class BabyTrackerAccountSensor(BabyTrackerEntity, SensorEntity):
    """A sensor reporting on the account as a whole."""

    entity_description: BabyTrackerAccountSensorEntityDescription

    def __init__(
        self,
        coordinator: BabyTrackerCoordinator,
        description: BabyTrackerAccountSensorEntityDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | dt.datetime:
        """Return the current value."""
        return self.entity_description.value_fn(self.account, dt_util.now())

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return supporting detail for this value."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.account)
