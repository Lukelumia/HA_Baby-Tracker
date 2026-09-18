"""Derive the dashboard-ready view of a Baby Tracker account.

The API layer gives a flat bag of :class:`~.api.Record` objects. Everything a
sensor needs — the latest event per logical key, today's counts, today's
volumes and durations, and the latest growth measurements — is computed here,
once per coordinator refresh, so entities stay trivial.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime as dt
from typing import Any

from .api import BabyRef, Record, SyncState
from .const import ACTIVITY_TYPES, NURSING_TYPES, TYPE_KEYS

#: Growth/temperature fields that become their own "latest value" sensor.
MEASUREMENT_FIELDS: tuple[str, ...] = (
    "weight_kg",
    "length_cm",
    "head_cm",
    "temperature_c",
)


@dataclass(slots=True)
class Measurement:
    """The most recent value of a measured field, and when it was taken."""

    value: float
    when: dt.datetime | None = None


@dataclass(slots=True)
class BabyStats:
    """Everything the entities show for one baby."""

    baby_id: str
    name: str
    gender: str | None = None
    dob: dt.datetime | None = None
    picture_id: str | None = None
    last: dict[str, Record] = field(default_factory=dict)
    today: dict[str, int] = field(default_factory=dict)
    total: dict[str, int] = field(default_factory=dict)
    measurements: dict[str, Measurement] = field(default_factory=dict)
    today_bottle_ml: float = 0.0
    today_nursing_seconds: int = 0
    today_sleep_seconds: int = 0
    sleeping: bool = False
    sleep_ends_at: dt.datetime | None = None

    def age_days(self, now: dt.datetime) -> int | None:
        """Age in whole days, or ``None`` if the birth date is unknown."""
        if self.dob is None:
            return None
        return max((now - self.dob).days, 0)


@dataclass(slots=True)
class AccountStats:
    """Account-wide figures, shown on the sync-group device."""

    account_id: int | None = None
    devices: list[dict[str, Any]] = field(default_factory=list)
    record_count: int = 0
    last: dict[str, Record] = field(default_factory=dict)
    today: dict[str, int] = field(default_factory=dict)
    total: dict[str, int] = field(default_factory=dict)
    today_pump_ml: float = 0.0
    synced_at: dt.datetime | None = None


@dataclass(slots=True)
class BabyTrackerData:
    """The coordinator's payload."""

    babies: dict[str, BabyStats] = field(default_factory=dict)
    account: AccountStats = field(default_factory=AccountStats)


def _record_keys(record: Record) -> tuple[str, ...]:
    """The logical keys one record counts towards."""
    keys = TYPE_KEYS.get(record.record_type, ())
    if record.record_type == "Diaper":
        extra = []
        if record.fields.get("wet"):
            extra.append("wet_diaper")
        if record.fields.get("dirty"):
            extra.append("dirty_diaper")
        return keys + tuple(extra)
    return keys


def _collect_babies(state: SyncState) -> dict[str, BabyStats]:
    """Find every baby in the account.

    A standalone ``Baby`` record is authoritative, but an account set up on
    iOS never publishes one — there, the baby is only ever seen nested inside
    each activity, so harvest those first and let a real record win.
    """
    refs: dict[str, BabyRef] = {}
    for record in state.records.values():
        ref = record.baby
        if ref is None:
            continue
        authoritative = record.record_type == "Baby"
        if ref.object_id not in refs or authoritative:
            refs[ref.object_id] = ref
        if authoritative:
            continue
        # Fill gaps from nested copies without overwriting better data.
        known = refs[ref.object_id]
        known.name = known.name or ref.name
        known.dob = known.dob or ref.dob
        known.gender = known.gender or ref.gender
        known.picture_id = known.picture_id or ref.picture_id

    return {
        ref.object_id: BabyStats(
            baby_id=ref.object_id,
            name=ref.name or "Baby",
            gender=ref.gender,
            dob=ref.dob,
            picture_id=ref.picture_id,
        )
        for ref in refs.values()
    }


def _tally(stats: BabyStats | AccountStats, record: Record, *, today: bool) -> None:
    """Fold one record into a stats bucket."""
    for key in _record_keys(record):
        stats.last[key] = record
        stats.total[key] = stats.total.get(key, 0) + 1
        if today:
            stats.today[key] = stats.today.get(key, 0) + 1


def _overlap_seconds(
    start: dt.datetime | None,
    duration: Any,
    window_start: dt.datetime,
    window_end: dt.datetime,
) -> int:
    """Seconds of an interval that fall inside a window."""
    if start is None or not duration:
        return 0
    try:
        end = start + dt.timedelta(seconds=int(duration))
    except TypeError, ValueError:
        return 0
    low = max(start, window_start)
    high = min(end, window_end)
    return int((high - low).total_seconds()) if high > low else 0


def _fold_account(account: AccountStats, record: Record, *, is_today: bool) -> None:
    """Fold a record that belongs to the account rather than to a baby."""
    _tally(account, record, today=is_today)
    if record.record_type == "Pump" and is_today:
        account.today_pump_ml += float(record.fields.get("amount_ml") or 0.0)


def _fold_baby(
    baby: BabyStats,
    record: Record,
    *,
    day_start: dt.datetime,
    now: dt.datetime,
    is_today: bool,
) -> None:
    """Fold one of a baby's activities into its stats."""
    _tally(baby, record, today=is_today)

    for name in MEASUREMENT_FIELDS:
        value = record.fields.get(name)
        if value is not None:
            baby.measurements[name] = Measurement(float(value), record.when)

    if is_today:
        if record.record_type in NURSING_TYPES:
            baby.today_nursing_seconds += int(record.fields.get("duration") or 0)
        elif "amount_ml" in record.fields:
            baby.today_bottle_ml += float(record.fields["amount_ml"] or 0.0)

    if record.record_type != "Sleep":
        return

    baby.today_sleep_seconds += _overlap_seconds(
        record.time, record.fields.get("duration"), day_start, now
    )
    ends_at = record.ends_at
    if ends_at is None or record.time is None:
        return
    if record.time <= now < ends_at:
        baby.sleeping = True
        baby.sleep_ends_at = ends_at
    elif baby.sleep_ends_at is None or ends_at > baby.sleep_ends_at:
        baby.sleep_ends_at = ends_at


def build_data(state: SyncState, now: dt.datetime) -> BabyTrackerData:
    """Turn the replayed record set into the coordinator payload.

    ``now`` must be timezone-aware and in Home Assistant's local timezone:
    "today" is a local calendar day, while the records themselves are UTC.
    """
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    babies = _collect_babies(state)
    account = AccountStats(
        account_id=state.account_id,
        devices=list(state.devices),
        record_count=len(state.records),
        synced_at=now,
    )

    activities = sorted(
        (
            record
            for record in state.records.values()
            if record.record_type in ACTIVITY_TYPES or record.record_type == "Pump"
        ),
        key=lambda record: (
            record.when or dt.datetime.min.replace(tzinfo=dt.UTC),
            record.sync_id,
        ),
    )

    for record in activities:
        when = record.when
        is_today = when is not None and when >= day_start
        baby = babies.get(record.baby_id) if record.baby_id else None
        if baby is None:
            _fold_account(account, record, is_today=is_today)
        else:
            _fold_baby(baby, record, day_start=day_start, now=now, is_today=is_today)

    for baby in babies.values():
        baby.today_bottle_ml = round(baby.today_bottle_ml, 1)
    account.today_pump_ml = round(account.today_pump_ml, 1)

    return BabyTrackerData(babies=babies, account=account)
