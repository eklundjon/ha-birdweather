"""The five legacy cold-map .storage files migrate into one species_meta store."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.birdweather.const import (
    CONF_STATION_ID,
    CONF_STATION_NAME,
    DOMAIN,
)
from custom_components.birdweather.coordinator import BirdWeatherCoordinator

SID = "777"


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=SID,
        data={CONF_STATION_ID: SID, CONF_STATION_NAME: "X"},
    )
    entry.add_to_hass(hass)
    return entry


async def test_legacy_cold_maps_consolidate_into_species_meta(
    hass: HomeAssistant, hass_storage
) -> None:
    # Seed two legacy per-map stores; species_meta is absent (pre-upgrade state).
    await Store(hass, 1, f"{DOMAIN}.{SID}.sp_codes").async_save({"Robin": "amerob"})
    await Store(hass, 1, f"{DOMAIN}.{SID}.links").async_save(
        {"amerob": {"ebird_url": "e"}}
    )

    coord = BirdWeatherCoordinator(hass, _entry(hass))
    await coord._load_stores()

    # Migrated into the in-memory maps...
    assert coord._sp_codes == {"Robin": "amerob"}
    assert coord._links_cache == {"amerob": {"ebird_url": "e"}}
    # ...written to the consolidated store...
    assert f"{DOMAIN}.{SID}.species_meta" in hass_storage
    meta = hass_storage[f"{DOMAIN}.{SID}.species_meta"]["data"]
    assert meta["sp_codes"] == {"Robin": "amerob"}
    assert meta["links"] == {"amerob": {"ebird_url": "e"}}
    # ...and the legacy per-map files are removed.
    for legacy in ("sp_codes", "sci_names", "image_urls", "image_attr", "links"):
        assert f"{DOMAIN}.{SID}.{legacy}" not in hass_storage


async def test_species_meta_is_authoritative_when_present(
    hass: HomeAssistant, hass_storage
) -> None:
    # When species_meta exists, it's used directly (no migration from legacy).
    await Store(hass, 1, f"{DOMAIN}.{SID}.species_meta").async_save(
        {"sp_codes": {"Owl": "brdowl"}, "sci_names": {}, "image_urls": {},
         "image_attr": {}, "links": {}}
    )
    coord = BirdWeatherCoordinator(hass, _entry(hass))
    await coord._load_stores()
    assert coord._sp_codes == {"Owl": "brdowl"}
