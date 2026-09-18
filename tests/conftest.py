"""Common fixtures for the Baby Tracker tests."""

import base64
from collections.abc import Generator
import datetime as dt
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.babytracker.api import (
    DEVICE_LIST_URL,
    LOGIN_URL,
    TRANSACTION_URL,
)
from custom_components.babytracker.const import CONF_DEVICE_UUID, DOMAIN
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.util import dt as dt_util

pytest_plugins = "pytest_homeassistant_custom_component"

OUR_UUID = "0F2C0C9E-0000-0000-0000-00000000HASS"
PHONE_UUID = "11111111-2222-3333-4444-555555555555"
BABY_ID = "BABY-1"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations in all tests."""


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "custom_components.babytracker.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A configured Baby Tracker account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="parent@example.com",
        unique_id="parent@example.com",
        data={
            CONF_EMAIL: "parent@example.com",
            CONF_PASSWORD: "hunter2",
            CONF_DEVICE_UUID: OUR_UUID,
        },
    )


def transaction(
    sync_id: int, obj: dict[str, Any], op: Any = "TransactionLogOpCodeInsert"
) -> dict[str, Any]:
    """Wrap a decoded object in a transaction-log entry."""
    payload = base64.b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")
    return {"SyncID": sync_id, "OPCode": op, "Transaction": payload}


def baby_node(object_id: str = BABY_ID) -> dict[str, Any]:
    """The baby object nested inside every activity."""
    return {
        "BCObjectType": "Baby",
        "objectID": object_id,
        "name": "Sam",
        "gender": "false",
        "dob": "2026-06-01 04:12:00 +0000",
        "pictureName": "PIC-1",
    }


def _fmt(when: dt.datetime) -> str:
    """Render a datetime the way the app does."""
    return when.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M:%S %z")


def _transactions() -> list[dict[str, Any]]:
    """A small transaction log, timed relative to now so "today" holds."""
    now = dt_util.utcnow()
    return [
        transaction(
            1,
            {
                "BCObjectType": "Diaper",
                "objectID": "D-1",
                "time": _fmt(now - dt.timedelta(hours=1)),
                "status": "DiaperStatusWet",
                "baby": baby_node(),
            },
        ),
        transaction(
            2,
            {
                "BCObjectType": "Formula",
                "objectID": "F-1",
                "time": _fmt(now - dt.timedelta(minutes=30)),
                "amount": {"englishMeasure": "false", "value": 150},
                "baby": baby_node(),
            },
        ),
    ]


@pytest.fixture
def mock_api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """A Baby Tracker account with one phone and two records in it."""
    aioclient_mock.post(LOGIN_URL, json={"AccountID": 4711})
    aioclient_mock.get(
        DEVICE_LIST_URL,
        json=[
            {"DeviceUUID": PHONE_UUID, "LastSyncID": 2, "DeviceName": "iPhone"},
        ],
    )
    aioclient_mock.get(f"{TRANSACTION_URL}{PHONE_UUID}/0", json=_transactions())
    aioclient_mock.get(f"{TRANSACTION_URL}{PHONE_UUID}/2", json=[])
    return aioclient_mock
