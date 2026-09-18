"""Tests for the integration's action and its translations."""

import json
from pathlib import Path

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.babytracker.const import (
    ATTR_CONFIG_ENTRY_ID,
    DOMAIN,
    SERVICE_REFRESH,
)
from custom_components.babytracker.sensor import ACCOUNT_SENSORS, BABY_SENSORS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.service import async_get_all_descriptions
from homeassistant.helpers.translation import async_get_translations

COMPONENT = Path(__file__).parent.parent / "custom_components" / "babytracker"


async def test_service_description(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """services.yaml and its strings load and describe the action."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    descriptions = await async_get_all_descriptions(hass)
    translations = await async_get_translations(hass, "en", "services", {DOMAIN})

    assert set(descriptions[DOMAIN][SERVICE_REFRESH]["fields"]) == {
        "config_entry_id",
        "full",
    }
    assert (
        translations[f"component.{DOMAIN}.services.{SERVICE_REFRESH}.name"] == "Refresh"
    )
    assert (
        f"component.{DOMAIN}.services.{SERVICE_REFRESH}.fields.full.description"
        in translations
    )


async def test_refresh_rejects_unknown_entry(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """Calling the action for another entry raises rather than crashing."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    other = MockConfigEntry(domain="sun")
    other.add_to_hass(hass)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_REFRESH,
            {ATTR_CONFIG_ENTRY_ID: other.entry_id},
            blocking=True,
        )


def test_every_translation_key_has_a_name() -> None:
    """No entity may fall back to its raw translation key in the UI."""
    strings = json.loads((COMPONENT / "strings.json").read_text())
    translations = json.loads((COMPONENT / "translations" / "en.json").read_text())
    assert strings == translations

    entity = strings["entity"]
    for description in (*BABY_SENSORS, *ACCOUNT_SENSORS):
        assert description.translation_key in entity["sensor"], description.key
    assert "sleeping" in entity["binary_sensor"]
    assert "photo" in entity["image"]
