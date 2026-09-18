"""Test the Baby Tracker config flow."""

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.babytracker.api import LOGIN_URL
from custom_components.babytracker.config_flow import CannotConnect, InvalidAuth
from custom_components.babytracker.const import CONF_DEVICE_UUID, DOMAIN
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

USER_INPUT = {CONF_EMAIL: "test@example.com", CONF_PASSWORD: "test-password"}

VALIDATE_INPUT = "custom_components.babytracker.config_flow.validate_input"


async def test_form(hass: HomeAssistant, mock_setup_entry: AsyncMock) -> None:
    """Test we get the form and can create an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    with patch(VALIDATE_INPUT, return_value={"title": USER_INPUT[CONF_EMAIL]}):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == USER_INPUT[CONF_EMAIL]
    assert result["data"][CONF_EMAIL] == USER_INPUT[CONF_EMAIL]
    assert result["data"][CONF_PASSWORD] == USER_INPUT[CONF_PASSWORD]
    # A stable UUID is minted here: the server keys our sync cursor on it.
    assert result["data"][CONF_DEVICE_UUID]
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    ("side_effect", "expected_error"),
    [
        (InvalidAuth, "invalid_auth"),
        (CannotConnect, "cannot_connect"),
        (Exception, "unknown"),
    ],
)
async def test_form_errors(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    side_effect: type[Exception],
    expected_error: str,
) -> None:
    """Test the form shows an error and recovers afterwards."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(VALIDATE_INPUT, side_effect=side_effect):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected_error}

    with patch(VALIDATE_INPUT, return_value={"title": USER_INPUT[CONF_EMAIL]}):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(mock_setup_entry.mock_calls) == 1


async def test_already_configured(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The same account cannot be added twice."""
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_EMAIL: "parent@example.com", CONF_PASSWORD: "whatever"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A new password replaces the old one on the existing entry."""
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch(VALIDATE_INPUT, return_value={"title": "parent@example.com"}):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new-password"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_PASSWORD] == "new-password"
    # The device UUID must survive, or the next sync re-downloads everything.
    assert config_entry.data[CONF_DEVICE_UUID] == "0F2C0C9E-0000-0000-0000-00000000HASS"


async def test_reauth_wrong_password(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A still-wrong password keeps the form open."""
    aioclient_mock.post(LOGIN_URL, status=401, text="nope")
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "still-wrong"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
