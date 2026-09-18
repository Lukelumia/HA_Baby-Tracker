"""End-to-end tests: set the entry up against a mocked cloud API."""

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.babytracker.api import LOGIN_URL
from custom_components.babytracker.const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_FULL,
    DOMAIN,
    SERVICE_REFRESH,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant


async def test_setup_creates_entities(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """The replayed log turns into sensors for the baby and the account."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED

    last_diaper = hass.states.get("sensor.sam_last_diaper")
    assert last_diaper is not None
    assert last_diaper.attributes["status"] == "Wet"
    assert last_diaper.attributes["device_class"] == "timestamp"

    assert hass.states.get("sensor.sam_diapers_today").state == "1"
    assert hass.states.get("sensor.sam_feeds_today").state == "1"
    assert hass.states.get("sensor.sam_bottle_volume_today").state == "150.0"
    assert hass.states.get("sensor.sam_last_bottle_amount").state == "150.0"
    assert hass.states.get("binary_sensor.sam_sleeping").state == "off"

    # Sleep is a core sensor: it exists from the start and reads unknown until
    # the first nap is logged. Nursing only appears once it has happened.
    assert hass.states.get("sensor.sam_last_sleep").state == "unknown"
    assert hass.states.get("sensor.sam_last_nursing") is None
    assert hass.states.get("sensor.sam_last_bath") is None

    # The account device carries the diagnostics.
    assert hass.states.get("sensor.parent_example_com_stored_records").state == "2"
    assert (
        hass.states.get("sensor.parent_example_com_devices_in_sync_group").state == "1"
    )


async def test_unload_entry(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """The entry unloads cleanly and its entities go away."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get("sensor.sam_last_diaper").state == "unavailable"


async def test_refresh_action(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """The refresh action re-reads the cursor-advanced log."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    calls_before = len(mock_api.mock_calls)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_REFRESH,
        {ATTR_CONFIG_ENTRY_ID: config_entry.entry_id, ATTR_FULL: True},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(mock_api.mock_calls) > calls_before
    assert hass.states.get("sensor.sam_diapers_today").state == "1"


async def test_bad_credentials_start_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A rejected password puts the entry into reauth instead of retrying."""
    aioclient_mock.post(LOGIN_URL, status=401, text="bad password")
    config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"]["source"] == SOURCE_REAUTH
    ]
    assert len(flows) == 1
