"""Client for the Baby Tracker (Nighp) cloud sync API.

Reconstructed from a static analysis of ``com.nighp.babytracker_android`` 5.07;
see ``claude/babytracker-sync-protocol.md`` in the project for the derivation.

This module deliberately has no Home Assistant imports: it is a plain
``aiohttp`` client that logs in, walks the per-device transaction log, replays
it into the current state and hands back normalised :class:`Record` objects.

The wire format has two dialects. The Android client serialises with Gson
(enums as constant names, real JSON booleans); the iOS client sends enum
ordinals and booleans as the *strings* ``"true"`` / ``"false"``. Every scalar
coming off the wire is therefore coerced explicitly.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass, field
import datetime as dt
import json
import logging
from typing import Any
import uuid

import aiohttp

_LOGGER = logging.getLogger(__name__)

ROOT_URL = "https://prodapp.babytrackers.com"
LOGIN_URL = f"{ROOT_URL}/session"
DEVICE_LIST_URL = f"{ROOT_URL}/account/device"
TRANSACTION_URL = f"{ROOT_URL}/account/transaction/"
PICTURE_URL = f"{ROOT_URL}/account/picture/"

#: The server returns at most this many transactions per request; a full page
#: means there is more to fetch.
PAGE_SIZE = 500

#: ``utility/DateTypeAdapter.java``: SimpleDateFormat("yyyy-MM-dd HH:mm:ss Z").
DATE_FORMAT = "%Y-%m-%d %H:%M:%S %z"
DATE_FORMAT_12H = "%Y-%m-%d %I:%M:%S %p %z"

OP_INSERT, OP_UPDATE, OP_DELETE, OP_RELIVE, OP_CONFLICT = range(5)
OP_NAMES = {
    OP_INSERT: "insert",
    OP_UPDATE: "update",
    OP_DELETE: "delete",
    OP_RELIVE: "relive",
    OP_CONFLICT: "conflict",
}
_OP_PREFIX = "TransactionLogOpCode"
_OP_BY_NAME = {f"{_OP_PREFIX}{name.capitalize()}": op for op, name in OP_NAMES.items()}

#: Enum ordinal -> constant name, from the decompiled enums. The Android client
#: sends the name, iOS sends the ordinal.
ENUMS: dict[str, dict[int, str]] = {
    "DiaperStatus": {0: "Wet", 1: "Poopy", 2: "Mixed", 3: "Dry"},
    "DiaperAmount": {
        0: "None",
        1: "Light",
        2: "Normal",
        3: "Heavy",
        4: "Overflow",
        5: "Noset",
    },
    "NursingFinishSide": {0: "NotSet", 1: "Left", 2: "Right"},
    "PumpFinishSide": {0: "None", 1: "Left", 2: "Right"},
    "PumpSides": {0: "Both", 1: "Left", 2: "Right"},
    "MediaType": {0: "Picture", 1: "Video", 2: "Audio"},
}

_ML_PER_OZ = 29.5735
_KG_PER_LB = 0.45359236
_INCH_PER_CM = 0.3937


class BabyTrackerError(Exception):
    """Any failure talking to the Baby Tracker API."""


class BabyTrackerAuthError(BabyTrackerError):
    """Wrong credentials, or the session expired and could not be renewed."""


class BabyTrackerConnectionError(BabyTrackerError):
    """The server could not be reached."""


# --------------------------------------------------------------------------- #
# scalar coercion
# --------------------------------------------------------------------------- #


def as_bool(value: Any, default: bool = False) -> bool:
    """Coerce a JSON boolean that may have been written as a string.

    The iOS client serialises booleans as ``"true"`` / ``"false"``, and
    ``bool("false")`` is ``True`` in Python, so every boolean off the wire has
    to go through here.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no", ""):
        return False
    return default


def parse_opcode(value: Any) -> int:
    """Normalise an ``OPCode`` field to its ordinal."""
    if isinstance(value, bool):
        return OP_INSERT
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    if text.lstrip("-").isdigit():
        return int(text)
    if text in _OP_BY_NAME:
        return _OP_BY_NAME[text]
    short = text.removeprefix(_OP_PREFIX).lower()
    for ordinal, name in OP_NAMES.items():
        if short == name:
            return ordinal
    _LOGGER.debug("Unknown OPCode %r, treating as insert", value)
    return OP_INSERT


def parse_date(value: Any) -> dt.datetime | None:
    """Parse the app's date format into an aware UTC datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return dt.datetime.fromtimestamp(float(value), tz=dt.UTC)
    text = str(value).strip()
    for fmt in (DATE_FORMAT, DATE_FORMAT_12H):
        try:
            return dt.datetime.strptime(text, fmt).astimezone(dt.UTC)
        except ValueError:
            continue
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _LOGGER.debug("Unparseable date %r", value)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def enum_name(enum: str, value: Any) -> str | None:
    """Normalise an enum field to its short constant name."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return ENUMS.get(enum, {}).get(value)
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        return ENUMS.get(enum, {}).get(int(text))
    if text.startswith(enum):
        return text[len(enum) :] or None
    return text or None


def measure(node: Any, kind: str) -> float | None:
    """Convert a ``Measure`` subclass to its metric value.

    Every measure serialises as ``{"englishMeasure": bool, "value": float}``
    where the number is in whichever unit the *writing* device used.
    """
    if not isinstance(node, dict):
        return None
    raw = node.get("value")
    if raw is None:
        return None
    try:
        value = float(raw)
    except TypeError, ValueError:
        return None
    if not as_bool(node.get("englishMeasure")):
        return round(value, 4)
    if kind == "volume":
        value *= _ML_PER_OZ
    elif kind == "weight":
        value *= _KG_PER_LB
    elif kind == "length":
        value /= _INCH_PER_CM
    elif kind == "temperature":
        value = (value - 32.0) * 5.0 / 9.0
    return round(value, 4)


def decode_transaction_payload(encoded: str) -> dict[str, Any]:
    """Base64-decode a ``Transaction`` blob into its JSON object."""
    raw = encoded.strip()
    padded = raw + "=" * (-len(raw) % 4)
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            decoded = json.loads(decoder(padded).decode("utf-8"))
        except binascii.Error, ValueError, UnicodeDecodeError:
            continue
        if isinstance(decoded, dict):
            return decoded
    raise BabyTrackerError(f"Could not decode transaction payload: {raw[:40]}...")


def _seconds(value: Any) -> int | None:
    """Coerce a duration field to whole seconds."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except TypeError, ValueError:
        return None


def _selection_name(node: Any) -> str | None:
    """Pull the display name out of an ``EditableSelection`` subtype."""
    if isinstance(node, dict):
        return node.get("name") or None
    if isinstance(node, str):
        return node or None
    return None


# --------------------------------------------------------------------------- #
# per-type field extraction
# --------------------------------------------------------------------------- #


def _fields_nursing(obj: dict[str, Any]) -> dict[str, Any]:
    """Nursing / NursingSession: per-side durations in seconds."""
    left = _seconds(obj.get("leftDuration")) or 0
    right = _seconds(obj.get("rightDuration")) or 0
    both = _seconds(obj.get("bothDuration")) or 0
    return {
        "left_duration": left,
        "right_duration": right,
        "both_duration": both,
        "duration": left + right + both,
        "finish_side": enum_name("NursingFinishSide", obj.get("finishSide")),
        "detailed": as_bool(obj.get("detailed")) if "detailed" in obj else None,
    }


def _fields_diaper(obj: dict[str, Any]) -> dict[str, Any]:
    """Diaper: status plus the wet/dirty split the dashboard cares about."""
    status = enum_name("DiaperStatus", obj.get("status"))
    return {
        "status": status,
        "amount": enum_name("DiaperAmount", obj.get("amount")),
        "wet": status in ("Wet", "Mixed"),
        "dirty": status in ("Poopy", "Mixed"),
        # iOS-only extras; the Android class does not declare these.
        "pee_colour": obj.get("peeColor"),
        "poo_colour": obj.get("pooColor"),
        "texture": obj.get("texture"),
    }


def _fields_sleep(obj: dict[str, Any]) -> dict[str, Any]:
    """Sleep: duration in seconds, counted from ``time``."""
    return {"duration": _seconds(obj.get("duration"))}


def _fields_bottle(obj: dict[str, Any]) -> dict[str, Any]:
    """Formula / Pumped: a volume."""
    return {"amount_ml": measure(obj.get("amount"), "volume")}


def _fields_other_feed(obj: dict[str, Any]) -> dict[str, Any]:
    """OtherFeed: a volume plus the user's own label for it."""
    return {
        "amount_ml": measure(obj.get("amount"), "volume"),
        "feed_type": _selection_name(obj.get("feedType")),
        "description": obj.get("desc") or None,
    }


def _fields_pump(obj: dict[str, Any]) -> dict[str, Any]:
    """Pump: volumes per side. Note a Pump record carries no baby."""
    return {
        "amount_ml": measure(obj.get("amount"), "volume"),
        "left_amount_ml": measure(obj.get("leftAmount"), "volume"),
        "right_amount_ml": measure(obj.get("rightAmount"), "volume"),
        "left_duration": _seconds(obj.get("leftDuration")),
        "right_duration": _seconds(obj.get("rightDuration")),
        "sides": enum_name("PumpSides", obj.get("sides")),
        "finish_side": enum_name("PumpFinishSide", obj.get("finishSide")),
        "label": obj.get("label") or None,
    }


def _fields_growth(obj: dict[str, Any]) -> dict[str, Any]:
    """Growth: any subset of weight, length and head circumference."""
    return {
        "weight_kg": measure(obj.get("weight"), "weight"),
        "length_cm": measure(obj.get("length"), "length"),
        "head_cm": measure(obj.get("head"), "length"),
    }


def _fields_temperature(obj: dict[str, Any]) -> dict[str, Any]:
    """Temperature: a single reading in degrees Celsius."""
    return {"temperature_c": measure(obj.get("temperature"), "temperature")}


def _fields_medication(obj: dict[str, Any]) -> dict[str, Any]:
    """Medication: dose plus the selected medication's name."""
    return {
        "amount": obj.get("amount"),
        "medication": _selection_name(obj.get("medicationSelection")),
    }


def _fields_milestone(obj: dict[str, Any]) -> dict[str, Any]:
    """Milestone: the selected milestone's name."""
    return {"milestone": _selection_name(obj.get("milestoneType"))}


def _fields_vaccine(obj: dict[str, Any]) -> dict[str, Any]:
    """Vaccine: the selected vaccine's name."""
    return {"vaccine": _selection_name(obj.get("vaccineType"))}


def _fields_other_activity(obj: dict[str, Any]) -> dict[str, Any]:
    """OtherActivity: a user-defined activity with an optional duration."""
    return {
        "description": _selection_name(obj.get("desc")),
        "duration": _seconds(obj.get("duration")),
    }


def _fields_picture(obj: dict[str, Any]) -> dict[str, Any]:
    """Picture: the media attached to another activity."""
    return {
        "file_name": obj.get("fileName"),
        "activity_id": obj.get("activityID"),
        "media_type": enum_name("MediaType", obj.get("mediaType")),
        "attached": as_bool(obj.get("attached")),
    }


_FIELD_EXTRACTORS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "Nursing": _fields_nursing,
    "NursingSession": _fields_nursing,
    "Diaper": _fields_diaper,
    "Sleep": _fields_sleep,
    "Formula": _fields_bottle,
    "Pumped": _fields_bottle,
    "Bottle": _fields_bottle,
    "OtherFeed": _fields_other_feed,
    "Pump": _fields_pump,
    "Growth": _fields_growth,
    "Temperature": _fields_temperature,
    "Medication": _fields_medication,
    "Milestone": _fields_milestone,
    "Vaccine": _fields_vaccine,
    "OtherActivity": _fields_other_activity,
    "Picture": _fields_picture,
}


def typed_fields(record_type: str, obj: dict[str, Any]) -> dict[str, Any]:
    """Extract the per-type fields of a decoded object, dropping empties."""
    extractor = _FIELD_EXTRACTORS.get(record_type)
    fields = extractor(obj) if extractor is not None else {}
    pictures = obj.get("pictureNote")
    if isinstance(pictures, list):
        ids = [p.get("objectID") for p in pictures if isinstance(p, dict)]
        if ids:
            fields["pictures"] = ids
    return {key: value for key, value in fields.items() if value is not None}


# --------------------------------------------------------------------------- #
# record model
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class BabyRef:
    """The baby an activity belongs to, as carried inside the activity."""

    object_id: str
    name: str | None = None
    gender: str | None = None
    dob: dt.datetime | None = None
    picture_id: str | None = None

    @classmethod
    def from_json(cls, node: Any) -> BabyRef | None:
        """Build a reference from a nested (or standalone) baby object."""
        if not isinstance(node, dict):
            return None
        object_id = node.get("objectID")
        if not object_id:
            return None
        return cls(
            object_id=object_id,
            name=node.get("name") or None,
            gender="male" if as_bool(node.get("gender")) else "female",
            dob=parse_date(node.get("dob")),
            picture_id=node.get("pictureName") or None,
        )

    def as_storage(self) -> dict[str, Any]:
        """Serialise for Home Assistant's ``Store``."""
        return {
            "object_id": self.object_id,
            "name": self.name,
            "gender": self.gender,
            "dob": self.dob.isoformat() if self.dob else None,
            "picture_id": self.picture_id,
        }

    @classmethod
    def from_storage(cls, data: dict[str, Any]) -> BabyRef:
        """Restore from ``as_storage`` output."""
        return cls(
            object_id=data["object_id"],
            name=data.get("name"),
            gender=data.get("gender"),
            dob=parse_date(data.get("dob")),
            picture_id=data.get("picture_id"),
        )


@dataclass(slots=True)
class Record:
    """One decoded Baby Tracker object, normalised for downstream use."""

    object_id: str
    record_type: str
    time: dt.datetime | None
    timestamp: dt.datetime | None
    sync_id: int
    device_uuid: str
    op: str
    deleted: bool
    note: str | None = None
    baby: BabyRef | None = None
    fields: dict[str, Any] = field(default_factory=dict)

    @property
    def baby_id(self) -> str | None:
        """The object id of the baby this record belongs to, if any."""
        return self.baby.object_id if self.baby else None

    @property
    def when(self) -> dt.datetime | None:
        """The event time, falling back to the last-modified time."""
        return self.time or self.timestamp

    @property
    def ends_at(self) -> dt.datetime | None:
        """End of the event for records that carry a duration."""
        duration = self.fields.get("duration")
        if self.time is None or not duration:
            return None
        return self.time + dt.timedelta(seconds=int(duration))

    def as_storage(self) -> dict[str, Any]:
        """Serialise for Home Assistant's ``Store``."""
        return {
            "object_id": self.object_id,
            "record_type": self.record_type,
            "time": self.time.isoformat() if self.time else None,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "sync_id": self.sync_id,
            "device_uuid": self.device_uuid,
            "op": self.op,
            "deleted": self.deleted,
            "note": self.note,
            "baby": self.baby.as_storage() if self.baby else None,
            "fields": self.fields,
        }

    @classmethod
    def from_storage(cls, data: dict[str, Any]) -> Record:
        """Restore from ``as_storage`` output."""
        baby = data.get("baby")
        return cls(
            object_id=data["object_id"],
            record_type=data["record_type"],
            time=parse_date(data.get("time")),
            timestamp=parse_date(data.get("timestamp")),
            sync_id=int(data.get("sync_id") or 0),
            device_uuid=data.get("device_uuid") or "",
            op=data.get("op") or "insert",
            deleted=bool(data.get("deleted")),
            note=data.get("note"),
            baby=BabyRef.from_storage(baby) if baby else None,
            fields=data.get("fields") or {},
        )


def build_record(entry: dict[str, Any], device_uuid: str) -> Record | None:
    """Turn one raw transaction-log entry into a :class:`Record`."""
    payload = entry.get("Transaction")
    if not payload:
        return None
    obj = decode_transaction_payload(payload)
    record_type = obj.get("BCObjectType")
    object_id = obj.get("objectID")
    if not record_type or not object_id:
        _LOGGER.debug("Skipping transaction without type/id: %s", list(obj)[:6])
        return None

    op = parse_opcode(entry.get("OPCode", OP_INSERT))
    baby = BabyRef.from_json(obj.get("baby"))
    if baby is None and record_type == "Baby":
        baby = BabyRef.from_json(obj)

    return Record(
        object_id=object_id,
        record_type=record_type,
        time=parse_date(obj.get("time")),
        timestamp=parse_date(obj.get("timestamp")),
        sync_id=int(entry.get("SyncID") or 0),
        device_uuid=device_uuid,
        op=OP_NAMES.get(op, "insert"),
        # A "relive" un-deletes a record, so it wins over the soft-delete flag.
        deleted=op == OP_DELETE or (op != OP_RELIVE and as_bool(obj.get("deleted"))),
        note=obj.get("note") or None,
        baby=baby,
        fields=typed_fields(record_type, obj),
    )


# --------------------------------------------------------------------------- #
# sync state
# --------------------------------------------------------------------------- #

STORAGE_VERSION = 1


@dataclass
class SyncState:
    """Everything needed to resume an incremental sync.

    ``device_uuid`` must stay stable across restarts: the server keys each
    device's sync cursor on it, so a fresh UUID forces a full re-download and
    registers another device on the account.
    """

    device_uuid: str = ""
    device_name: str = "Home Assistant"
    account_id: int | None = None
    cursors: dict[str, int] = field(default_factory=dict)
    records: dict[str, Record] = field(default_factory=dict)
    devices: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Generate a device UUID if none was restored."""
        if not self.device_uuid:
            self.device_uuid = str(uuid.uuid4()).upper()

    def apply(self, record: Record) -> None:
        """Replay one transaction over the current state.

        The app's merge keeps the last write per object id; a delete removes
        the object and a later relive brings it back.
        """
        existing = self.records.get(record.object_id)
        if (
            existing is not None
            and existing.device_uuid == record.device_uuid
            and existing.sync_id > record.sync_id
        ):
            return
        if record.deleted:
            self.records.pop(record.object_id, None)
            return
        self.records[record.object_id] = record

    def as_storage(self) -> dict[str, Any]:
        """Serialise the whole state for Home Assistant's ``Store``."""
        return {
            "device_uuid": self.device_uuid,
            "account_id": self.account_id,
            "cursors": self.cursors,
            "records": [record.as_storage() for record in self.records.values()],
        }

    @classmethod
    def from_storage(cls, data: dict[str, Any] | None, device_name: str) -> SyncState:
        """Restore from ``as_storage`` output, tolerating a missing store."""
        data = data or {}
        state = cls(
            device_uuid=data.get("device_uuid") or "",
            device_name=device_name,
            account_id=data.get("account_id"),
            cursors={str(k): int(v) for k, v in (data.get("cursors") or {}).items()},
        )
        for raw in data.get("records") or []:
            try:
                record = Record.from_storage(raw)
            except KeyError, TypeError, ValueError:
                _LOGGER.debug("Dropping unreadable stored record")
                continue
            state.records[record.object_id] = record
        return state


# --------------------------------------------------------------------------- #
# the client
# --------------------------------------------------------------------------- #


class BabyTrackerClient:
    """Async, read-only client for the Baby Tracker cloud sync API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        state: SyncState | None = None,
    ) -> None:
        """Initialise the client with a session that keeps its own cookie jar."""
        self._session = session
        self._email = email
        self._password = password
        self.state = state or SyncState()
        self._logged_in = False

    @property
    def account_id(self) -> int | None:
        """The account id the server reported at login."""
        return self.state.account_id

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: Any = None,
        allow_retry: bool = True,
        raw: bool = False,
    ) -> Any:
        """Perform one request, re-authenticating once on a 401."""
        headers = {"Connection": "close"}
        data = None
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            headers["charset"] = "utf-8"
            data = json.dumps(json_body).encode("utf-8")

        try:
            async with self._session.request(
                method, url, data=data, headers=headers
            ) as resp:
                if resp.status == 401:
                    if not allow_retry:
                        raise BabyTrackerAuthError("Authentication failed (HTTP 401)")
                    _LOGGER.debug("Session expired, logging in again")
                    await self.async_login()
                    return await self._request(
                        method, url, json_body=json_body, allow_retry=False, raw=raw
                    )
                body = await (resp.read() if raw else resp.text())
                if resp.status not in (200, 409):
                    snippet = body[:200] if isinstance(body, str) else f"{len(body)}B"
                    raise BabyTrackerError(
                        f"{method} {url} returned HTTP {resp.status}: {snippet}"
                    )
                return body
        except aiohttp.ClientError as err:
            raise BabyTrackerConnectionError(f"{method} {url} failed: {err}") from err
        except TimeoutError as err:
            raise BabyTrackerConnectionError(f"{method} {url} timed out") from err

    async def async_login(self) -> int | None:
        """``POST /session`` and keep the session cookie."""
        payload = {
            "Device": {
                "DeviceUUID": self.state.device_uuid,
                "DeviceName": self.state.device_name,
                "DeviceOSInfo": "Home Assistant",
            },
            "EmailAddress": self._email,
            "Password": self._password,
            "AppInfo": {"AccountType": 0, "AppType": 0},
        }
        text = await self._request(
            "POST", LOGIN_URL, json_body=payload, allow_retry=False
        )
        try:
            self.state.account_id = (json.loads(text) or {}).get("AccountID")
        except ValueError:
            self.state.account_id = None
        self._logged_in = True
        _LOGGER.debug("Logged in, account id %s", self.state.account_id)
        return self.state.account_id

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """``GET /account/device`` -> the devices in this sync group."""
        text = await self._request("GET", DEVICE_LIST_URL)
        try:
            devices = json.loads(text) or []
        except ValueError as err:
            raise BabyTrackerError("Device list was not valid JSON") from err
        return [
            {
                "uuid": device["DeviceUUID"],
                "last_sync_id": int(device.get("LastSyncID") or 0),
                "name": device.get("DeviceName"),
                "os": device.get("DeviceOSInfo"),
            }
            for device in devices
            if isinstance(device, dict) and device.get("DeviceUUID")
        ]

    async def async_get_transactions(
        self, device_uuid: str, since_sync_id: int = 0
    ) -> list[dict[str, Any]]:
        """One page of a device's transaction log (at most ``PAGE_SIZE``)."""
        text = await self._request(
            "GET", f"{TRANSACTION_URL}{device_uuid}/{since_sync_id}"
        )
        try:
            page = json.loads(text) or []
        except ValueError as err:
            raise BabyTrackerError("Transaction page was not valid JSON") from err
        return [entry for entry in page if isinstance(entry, dict)]

    async def async_get_picture(self, object_id: str) -> bytes:
        """``GET /account/picture/{objectID}`` -> raw image bytes."""
        return await self._request("GET", f"{PICTURE_URL}{object_id}", raw=True)

    async def _async_sync_device(self, device: dict[str, Any]) -> int:
        """Page through one device's log from our stored cursor."""
        device_uuid = device["uuid"]
        cursor = self.state.cursors.get(device_uuid, 0)
        if cursor > device["last_sync_id"]:
            _LOGGER.debug("Cursor for %s rolled back, re-seeding", device_uuid)
            cursor = 0

        applied = 0
        while True:
            page = await self.async_get_transactions(device_uuid, cursor)
            if not page:
                return applied
            for entry in page:
                try:
                    record = build_record(entry, device_uuid)
                except BabyTrackerError as err:
                    _LOGGER.warning(
                        "Skipping unreadable transaction %s: %s",
                        entry.get("SyncID"),
                        err,
                    )
                    continue
                if record is not None:
                    self.state.apply(record)
                    applied += 1
            cursor = int(page[-1].get("SyncID") or cursor)
            self.state.cursors[device_uuid] = cursor
            if len(page) < PAGE_SIZE:
                return applied

    async def async_sync(self, *, full: bool = False) -> int:
        """Download every device's log, replay it, and return the entry count.

        Pass ``full=True`` to ignore the stored cursors and start over.
        """
        if full or not self._logged_in:
            await self.async_login()
        if full:
            self.state.cursors.clear()
            self.state.records.clear()

        devices = await self.async_get_devices()
        self.state.devices = devices
        applied = 0
        for device in devices:
            if device["uuid"] == self.state.device_uuid:
                continue  # our own cursor; the app skips itself too
            applied += await self._async_sync_device(device)

        _LOGGER.debug(
            "Applied %d transaction(s); %d live record(s)",
            applied,
            len(self.state.records),
        )
        return applied
