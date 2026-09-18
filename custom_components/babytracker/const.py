"""Constants for the Baby Tracker integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "babytracker"

# Cloud sync API of the Baby Tracker (Nighp) app.
BASE_URL: Final = "https://prodapp.babytrackers.com"

# Stored in the config entry so the server keeps our sync cursor between runs.
CONF_DEVICE_UUID: Final = "device_uuid"

#: The app syncs on open and on push; the cursors make each poll cheap, so a
#: couple of minutes is plenty and stays friendly to the free service.
DEFAULT_SCAN_INTERVAL: Final = timedelta(minutes=2)

#: Key of the ``Store`` holding the device UUID, the per-device cursors and the
#: replayed records, so a restart does not force a full re-download.
STORAGE_KEY: Final = f"{DOMAIN}.sync"
STORAGE_VERSION: Final = 1

#: How this client names itself in the account's device list.
DEVICE_NAME: Final = "Home Assistant"

#: Device registry metadata.
MANUFACTURER: Final = "Nighp Software"
ACCOUNT_MODEL: Final = "Baby Tracker account"
BABY_MODEL: Final = "Baby"
CONFIGURATION_URL: Final = "https://www.babytrackers.com"

SERVICE_REFRESH: Final = "refresh"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_FULL: Final = "full"

# --- record types ---------------------------------------------------------- #

NURSING_TYPES: Final = frozenset({"Nursing", "NursingSession"})
BOTTLE_TYPES: Final = frozenset({"Bottle", "Formula", "Pumped", "OtherFeed"})
FEED_TYPES: Final = NURSING_TYPES | BOTTLE_TYPES

#: Dated events attached to a baby. ``Pump`` is deliberately absent: a pumping
#: record carries no baby and belongs to the account instead.
ACTIVITY_TYPES: Final = frozenset(
    {
        "Bath",
        "Diaper",
        "Growth",
        "Journal",
        "Joy",
        "Medication",
        "Milestone",
        "OtherActivity",
        "Sleep",
        "Temperature",
        "Vaccine",
    }
    | FEED_TYPES
)

#: ``record_type`` -> the logical keys it feeds. Entities are keyed on these,
#: so "bottle" covers formula, expressed milk and other feeds alike.
TYPE_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "Nursing": ("nursing", "feed"),
    "NursingSession": ("nursing", "feed"),
    "Bottle": ("bottle", "feed"),
    "Formula": ("formula", "bottle", "feed"),
    "Pumped": ("pumped", "bottle", "feed"),
    "OtherFeed": ("other_feed", "bottle", "feed"),
    "Diaper": ("diaper",),
    "Sleep": ("sleep",),
    "Bath": ("bath",),
    "Growth": ("growth",),
    "Temperature": ("temperature",),
    "Medication": ("medication",),
    "Milestone": ("milestone",),
    "Vaccine": ("vaccine",),
    "Journal": ("journal",),
    "Joy": ("joy",),
    "OtherActivity": ("other_activity",),
    "Pump": ("pump",),
}

#: Values of a ``Diaper`` record's status field, for the enum sensor.
DIAPER_STATUSES: Final = ["Wet", "Poopy", "Mixed", "Dry"]
