from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.loader import async_get_integration

from .const import CONF_STATION_ID, DOMAIN
from .coordinator import BirdWeatherConfigEntry, BirdWeatherCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

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

    # One-time: clear a serial_number stamped on the device by older versions.
    # A station ID isn't a serial number, and HA labels it "Serial number" on the
    # device page. HA preserves device fields an integration stops supplying, so
    # dropping it from DeviceInfo doesn't clear an already-registered device —
    # do it explicitly here. Idempotent (no-op once cleared).
    device_reg = dr.async_get(hass)
    device = device_reg.async_get_device(
        identifiers={(DOMAIN, entry.data[CONF_STATION_ID])}
    )
    if device is not None and device.serial_number is not None:
        device_reg.async_update_device(device.id, serial_number=None)

    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: BirdWeatherConfigEntry
) -> None:
    # Reload so every knob takes effect — including the poll interval, which is
    # read in the coordinator's __init__ and so needs a fresh coordinator (a bare
    # refresh wouldn't pick it up).
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BirdWeatherConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: BirdWeatherConfigEntry) -> None:
    """Clean up a removed station's persistent .storage files (10 per station).

    All stores are namespaced by station id, so they're safe to delete regardless
    of any other configured stations. (BirdWeather streams audio, so there's no
    on-disk media cache to remove.)
    """
    await BirdWeatherCoordinator.async_remove_stores(
        hass, entry.data[CONF_STATION_ID]
    )
