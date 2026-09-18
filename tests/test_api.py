"""Tests for the Baby Tracker API layer."""

import datetime as dt

import pytest

from custom_components.babytracker.api import (
    OP_DELETE,
    OP_INSERT,
    OP_RELIVE,
    SyncState,
    as_bool,
    build_record,
    decode_transaction_payload,
    enum_name,
    measure,
    parse_date,
    parse_opcode,
)

from .conftest import PHONE_UUID, baby_node, transaction


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        ("true", True),
        # The iOS client writes booleans as strings; bool("false") is True.
        ("false", False),
        (1, True),
        (0, False),
        (None, False),
    ],
)
def test_as_bool(value: object, expected: bool) -> None:
    """Both wire dialects of a boolean are read correctly."""
    assert as_bool(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("TransactionLogOpCodeInsert", OP_INSERT),
        ("TransactionLogOpCodeDelete", OP_DELETE),
        (3, OP_RELIVE),
        ("2", OP_DELETE),
        ("nonsense", OP_INSERT),
    ],
)
def test_parse_opcode(value: object, expected: int) -> None:
    """Names, ordinals and rubbish all resolve to an ordinal."""
    assert parse_opcode(value) == expected


def test_parse_date() -> None:
    """Both date formats parse to aware UTC datetimes."""
    assert parse_date("2026-09-18 08:30:00 +0000") == dt.datetime(
        2026, 9, 18, 8, 30, tzinfo=dt.UTC
    )
    assert parse_date("2026-09-18 08:30:00 AM +0000") == dt.datetime(
        2026, 9, 18, 8, 30, tzinfo=dt.UTC
    )
    assert parse_date("") is None
    assert parse_date("not a date") is None


@pytest.mark.parametrize(
    ("node", "kind", "expected"),
    [
        ({"englishMeasure": False, "value": 100}, "volume", 100.0),
        ({"englishMeasure": True, "value": 4}, "volume", 118.294),
        # "false" must not be read as truthy, or 100 mL becomes 100 oz.
        ({"englishMeasure": "false", "value": 100}, "volume", 100.0),
        ({"englishMeasure": True, "value": 10}, "weight", 4.5359),
        ({"englishMeasure": True, "value": 98.6}, "temperature", 37.0),
        ({"value": None}, "volume", None),
        ("nonsense", "volume", None),
    ],
)
def test_measure(node: object, kind: str, expected: float | None) -> None:
    """Measures convert to metric whichever unit they were written in."""
    assert measure(node, kind) == expected


def test_enum_name() -> None:
    """Android sends constant names, iOS sends ordinals."""
    assert enum_name("DiaperStatus", "DiaperStatusMixed") == "Mixed"
    assert enum_name("DiaperStatus", 2) == "Mixed"
    assert enum_name("DiaperStatus", None) is None


def test_decode_transaction_payload_rejects_rubbish() -> None:
    """An undecodable payload raises rather than returning nonsense."""
    with pytest.raises(Exception, match="Could not decode"):
        decode_transaction_payload("!!!not base64!!!")


def test_build_record_android_nursing() -> None:
    """An Android nursing record keeps its per-side durations."""
    record = build_record(
        transaction(
            10,
            {
                "BCObjectType": "Nursing",
                "objectID": "N-1",
                "time": "2026-09-18 08:30:00 +0000",
                "timestamp": "2026-09-18 08:55:00 +0000",
                "note": "sleepy",
                "leftDuration": 300,
                "rightDuration": 420,
                "bothDuration": 0,
                "finishSide": "NursingFinishSideRight",
                "baby": baby_node(),
            },
        ),
        PHONE_UUID,
    )

    assert record is not None
    assert record.record_type == "Nursing"
    assert record.baby_id == "BABY-1"
    assert record.baby is not None
    assert record.baby.name == "Sam"
    assert record.note == "sleepy"
    assert record.fields["duration"] == 720
    assert record.fields["finish_side"] == "Right"
    assert record.ends_at == dt.datetime(2026, 9, 18, 8, 42, tzinfo=dt.UTC)


def test_build_record_ios_dialect() -> None:
    """Ordinal enums, string booleans and unknown fields are all tolerated."""
    record = build_record(
        transaction(
            11,
            {
                "BCObjectType": "Diaper",
                "objectID": "D-1",
                "time": "2026-09-18 09:00:00 +0000",
                "status": 2,
                "amount": 3,
                "peeColor": 1,
                "flag": 5,
                "deleted": "false",
                "baby": baby_node(),
            },
            op=0,
        ),
        PHONE_UUID,
    )

    assert record is not None
    assert record.deleted is False
    assert record.fields["status"] == "Mixed"
    assert record.fields["amount"] == "Heavy"
    assert record.fields["wet"] is True
    assert record.fields["dirty"] is True


def test_build_record_skips_unusable() -> None:
    """Entries without a payload or a type are dropped, not raised on."""
    assert build_record({"SyncID": 1}, PHONE_UUID) is None
    assert build_record(transaction(1, {"objectID": "X"}), PHONE_UUID) is None


def test_state_merge_delete_and_relive() -> None:
    """Later writes win, a delete removes and a relive brings it back."""
    state = SyncState(device_uuid="OURS")
    obj = {
        "BCObjectType": "Bath",
        "objectID": "B-1",
        "time": "2026-09-18 18:00:00 +0000",
        "baby": baby_node(),
    }

    state.apply(build_record(transaction(1, obj), PHONE_UUID))
    assert "B-1" in state.records

    state.apply(
        build_record(transaction(2, obj, op="TransactionLogOpCodeDelete"), PHONE_UUID)
    )
    assert "B-1" not in state.records

    state.apply(
        build_record(transaction(3, obj, op="TransactionLogOpCodeRelive"), PHONE_UUID)
    )
    assert "B-1" in state.records


def test_state_ignores_stale_sync_id() -> None:
    """An out-of-order page cannot undo a newer write from the same device."""
    state = SyncState(device_uuid="OURS")
    obj = {
        "BCObjectType": "Joy",
        "objectID": "J-1",
        "time": "2026-09-18 12:00:00 +0000",
        "note": "new",
        "baby": baby_node(),
    }
    state.apply(build_record(transaction(9, obj), PHONE_UUID))
    state.apply(build_record(transaction(4, {**obj, "note": "old"}), PHONE_UUID))

    assert state.records["J-1"].note == "new"


def test_state_storage_roundtrip() -> None:
    """The store keeps everything a restart needs."""
    state = SyncState(device_uuid="OURS")
    state.account_id = 4711
    state.cursors[PHONE_UUID] = 12
    state.apply(
        build_record(
            transaction(
                12,
                {
                    "BCObjectType": "Growth",
                    "objectID": "G-1",
                    "time": "2026-09-18 10:00:00 +0000",
                    "weight": {"englishMeasure": False, "value": 5.4},
                    "baby": baby_node(),
                },
            ),
            PHONE_UUID,
        )
    )

    restored = SyncState.from_storage(state.as_storage(), "Home Assistant")

    assert restored.device_uuid == "OURS"
    assert restored.account_id == 4711
    assert restored.cursors == {PHONE_UUID: 12}
    assert restored.records["G-1"].fields["weight_kg"] == 5.4
    assert restored.records["G-1"].baby is not None
    assert restored.records["G-1"].baby.name == "Sam"


def test_state_generates_a_device_uuid() -> None:
    """A missing UUID is generated rather than left empty."""
    assert SyncState().device_uuid
    assert SyncState.from_storage(None, "Home Assistant").device_uuid
