"""Load the integration into a real Home Assistant install and check it works.

The pytest suite runs against the Home Assistant version that
``pytest-homeassistant-custom-component`` pins. This script is the other half:
it installs the integration the way HACS does — a copy under
``custom_components/`` in a config directory — and boots the Home Assistant
release that is actually installed, so a breaking change upstream shows up here
before a user hits it.

Run it with ``python scripts/smoke_test.py`` in an environment that has
``homeassistant`` installed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import sys
import tempfile

from homeassistant import bootstrap, loader
from homeassistant.config_entries import SOURCE_USER, ConfigEntries
from homeassistant.const import __version__ as ha_version
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

DOMAIN = "babytracker"
PLATFORMS = ("binary_sensor", "config_flow", "image", "sensor")
REPO = Path(__file__).resolve().parent.parent


def _install(config_dir: Path) -> None:
    """Copy the integration in the way HACS would."""
    target = config_dir / "custom_components" / DOMAIN
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        REPO / "custom_components" / DOMAIN,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


async def _check(config_dir: Path) -> None:
    """Boot Home Assistant and exercise the integration's entry points."""
    hass = HomeAssistant(str(config_dir))
    hass.config.config_dir = str(config_dir)
    hass.config.skip_pip = True
    loader.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    await bootstrap.async_load_base_functionality(hass)
    await hass.async_start()
    try:
        integration = await loader.async_get_integration(hass, DOMAIN)
        assert integration.is_built_in is False, "should load as a custom integration"
        print(f"manifest ok: {integration.name} {integration.version}")

        # Every module Home Assistant will import at runtime must import here.
        await integration.async_get_component()
        await integration.async_get_platforms(PLATFORMS)
        print(f"imported: {', '.join(PLATFORMS)}")

        # async_setup registers the integration's action.
        assert await async_setup_component(hass, DOMAIN, {}), "async_setup failed"
        await hass.async_block_till_done()
        assert hass.services.has_service(DOMAIN, "refresh"), "action not registered"
        print("action registered: babytracker.refresh")

        # The user-facing config flow must open (no credentials needed for the
        # form itself, so this stops short of talking to the cloud API).
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM, result["type"]
        assert result["step_id"] == "user", result["step_id"]
        print("config flow opens the user step")
    finally:
        await hass.async_stop()


def main() -> int:
    """Install the integration into a throwaway config dir and check it."""
    print(f"Home Assistant {ha_version} on Python {sys.version.split()[0]}")
    with tempfile.TemporaryDirectory() as tmp:
        config_dir = Path(tmp)
        _install(config_dir)
        asyncio.run(_check(config_dir))
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
