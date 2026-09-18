"""Tests for the derived, dashboard-ready view of an account."""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from custom_components.babytracker.api import SyncState, build_record
from custom_components.babytracker.models import build_data

from .conftest import PHONE_UUID, baby_node, transaction

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
NOW = dt.datetime(2026, 9, 18, 15, 0, tzinfo=AMSTERDAM)  # 13:00 UTC


def _activity(sync_id: int, obj: dict) -> dict:
    """An activity transaction belonging to our test baby."""
    return transaction(sync_id, {"baby": baby_node(), **obj})


@pytest.fixture
def state() -> SyncState:
    """An account with a day's worth of activity in it."""
    state = SyncState(device_uuid="OURS")
    state.account_id = 4711
    state.devices = [{"uuid": PHONE_UUID, "last_sync_id": 6, "name": "iPhone"}]
    entries = [
        _activity(
            1,
            {
                "BCObjectType": "Nursing",
                "objectID": "N-1",
                "time": "2026-09-18 08:30:00 +0000",
                "leftDuration": 420,
                "rightDuration": 300,
            },
        ),
        _activity(
            2,
            {
                "BCObjectType": "Formula",
                "objectID": "F-1",
                "time": "2026-09-18 12:00:00 +0000",
                "amount": {"englishMeasure": "false", "value": 120},
            },
        ),
        _activity(
            3,
            {
                "BCObjectType": "Diaper",
                "objectID": "D-1",
                "time": "2026-09-18 09:00:00 +0000",
                "status": 2,
            },
        ),
        _activity(
            4,
            {
                "BCObjectType": "Sleep",
                "objectID": "S-1",
                "time": "2026-09-18 12:40:00 +0000",
                "duration": 3600,
            },
        ),
        _activity(
            5,
            {
                "BCObjectType": "Growth",
                "objectID": "G-1",
                "time": "2026-09-15 10:00:00 +0000",
                "weight": {"englishMeasure": False, "value": 5.4},
                "length": {"englishMeasure": False, "value": 58},
            },
        ),
        # A Pump record carries no baby: it belongs to the account.
        transaction(
            6,
            {
                "BCObjectType": "Pump",
                "objectID": "P-1",
                "time": "2026-09-18 07:00:00 +0000",
                "amount": {"englishMeasure": False, "value": 100},
            },
        ),
    ]
    for entry in entries:
        record = build_record(entry, PHONE_UUID)
        assert record is not None
        state.apply(record)
    return state


def test_baby_is_harvested_from_activities(state: SyncState) -> None:
    """An iOS account never publishes a Baby record; the nested one is enough."""
    baby = build_data(state, NOW).babies["BABY-1"]

    assert baby.name == "Sam"
    assert baby.gender == "female"
    assert baby.picture_id == "PIC-1"
    assert baby.dob == dt.datetime(2026, 6, 1, 4, 12, tzinfo=dt.UTC)
    assert baby.age_days(NOW) == 109


def test_today_counts(state: SyncState) -> None:
    """Every logical key a record feeds is counted."""
    baby = build_data(state, NOW).babies["BABY-1"]

    assert baby.today["feed"] == 2
    assert baby.today["nursing"] == 1
    assert baby.today["bottle"] == 1
    assert baby.today["formula"] == 1
    assert baby.today["diaper"] == 1
    assert baby.today["wet_diaper"] == 1
    assert baby.today["dirty_diaper"] == 1
    # Three days ago, so counted in the total but not in today.
    assert baby.total["growth"] == 1
    assert "growth" not in baby.today


def test_latest_event_per_key(state: SyncState) -> None:
    """The latest feed is the bottle, not the earlier nursing."""
    baby = build_data(state, NOW).babies["BABY-1"]

    assert baby.last["feed"].object_id == "F-1"
    assert baby.last["nursing"].object_id == "N-1"
    assert baby.last["nursing"].fields["duration"] == 720


def test_daily_totals(state: SyncState) -> None:
    """Volumes and durations add up over the local calendar day."""
    baby = build_data(state, NOW).babies["BABY-1"]

    assert baby.today_bottle_ml == 120.0
    assert baby.today_nursing_seconds == 720


def test_sleep_in_progress(state: SyncState) -> None:
    """A nap counts as running until its start plus duration has passed."""
    baby = build_data(state, NOW).babies["BABY-1"]

    assert baby.sleeping is True
    assert baby.sleep_ends_at == dt.datetime(2026, 9, 18, 13, 40, tzinfo=dt.UTC)
    # Only the part of the nap that has already happened today counts.
    assert baby.today_sleep_seconds == 1200


def test_sleep_finished(state: SyncState) -> None:
    """After the nap ends the baby is awake again."""
    later = NOW + dt.timedelta(hours=2)
    baby = build_data(state, later).babies["BABY-1"]

    assert baby.sleeping is False
    assert baby.today_sleep_seconds == 3600


def test_measurements(state: SyncState) -> None:
    """Growth readings survive as the latest value per field."""
    baby = build_data(state, NOW).babies["BABY-1"]

    assert baby.measurements["weight_kg"].value == 5.4
    assert baby.measurements["length_cm"].value == 58.0
    assert "head_cm" not in baby.measurements


def test_account_level_pumping(state: SyncState) -> None:
    """A Pump record has no baby, so it lands on the account."""
    account = build_data(state, NOW).account

    assert account.account_id == 4711
    assert account.total["pump"] == 1
    assert account.today_pump_ml == 100.0
    assert account.record_count == 6
    assert len(account.devices) == 1
