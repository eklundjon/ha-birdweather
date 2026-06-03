from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .coordinator import BirdWeatherConfigEntry, BirdWeatherCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = ["sensor", "binary_sensor"]

_CARDS = [
    ("/birdweather/birdweather-bird-card.js",      "www/birdweather-bird-card.js"),
    ("/birdweather/birdweather-bird-list-card.js", "www/birdweather-details-card.js"),
]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register static paths and inject card JS once at integration load time."""
    www = Path(__file__).parent
    await hass.http.async_register_static_paths(
        [StaticPathConfig(url, str(www / path)) for url, path in _CARDS]
    )
    integration = await async_get_integration(hass, DOMAIN)
    version = integration.version or "dev"
    for url, _ in _CARDS:
        add_extra_js_url(hass, f"{url}?v={version}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BirdWeatherConfigEntry) -> bool:
    coordinator = BirdWeatherCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: BirdWeatherConfigEntry
) -> None:
    coordinator: BirdWeatherCoordinator = entry.runtime_data
    await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: BirdWeatherConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
