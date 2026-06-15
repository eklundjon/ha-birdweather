"""End-to-end entry setup: a mocked poll wires up the real entities.

Setting the entry up runs async_setup_entry -> the coordinator's first refresh
(against a stubbed client) -> both platforms, so this exercises every sensor's
native_value / attributes and the binary sensor in one pass.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.birdweather.const import (
    CONF_STATION_ID,
    CONF_STATION_NAME,
    DOMAIN,
)
from custom_components.birdweather.coordinator import BirdWeatherCoordinator

from .coordinator_helpers import make_client

STATION_ID = "12345"
_NOW = datetime.now(UTC)


def _iso(minutes_ago: int) -> str:
    return (_NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _raw(cn, sp, minutes_ago):
    return {
        "cn": cn, "sn": f"{cn} sci", "spCode": sp, "dt": _iso(minutes_ago),
        "image": "i.jpg", "audio": None, "confidence": 0.9,
    }


_BASELINE = [
    {"bird": "American Robin", "count": 500},
    {"bird": "Northern Cardinal", "count": 200},
    {"bird": "Barred Owl", "count": 5},
]
_DETECTIONS = {"detections": [
    _raw("American Robin", "amerob", 30),
    _raw("Northern Cardinal", "norcar", 45),
    _raw("Barred Owl", "brdowl", 300),
]}
_OVERVIEW = {
    "today_total": 142,
    "typical_daily": 88,
    "new_species_window": 4,
    # earliestDetectionAt is a full tz-aware ISO timestamp (see client.get_overview).
    "history_earliest": "2024-01-01T08:30:00-05:00",
    "lifetime_species": 57,
    "today_top": [{"species": "American Robin", "sp_code": "amerob", "count": 120}],
}
_PUC_SENSORS = {
    "environment": {"temperature": 21.5, "humidity": 55, "barometricPressure": 1013.2,
                    "soundPressureLevel": 47, "voc": 0.5, "aqi": 12},
    "light": {"clear": 1600},
    "system": {"batteryVoltage": 5.1, "powerSource": "USB-C", "wifiRssi": -55,
               "sdAvailable": "30000000000", "sdCapacity": "31000000000"},
}


async def _setup_entry(hass: HomeAssistant, *, sensors=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=STATION_ID,
        data={CONF_STATION_ID: STATION_ID, CONF_STATION_NAME: "Backyard"},
        options={},
    )
    entry.add_to_hass(hass)
    client = make_client(
        baseline=_BASELINE, detections=_DETECTIONS, overview=_OVERVIEW,
        time_of_day={"by_species": {}, "station": ([0] * 7 + [99] + [0] * 16)},
        sensors=sensors if sensors is not None else {},
    )
    with (
        # The component-level async_setup only registers card JS + static paths
        # (needs the frontend wheel); not what we're exercising here.
        patch("custom_components.birdweather.async_setup", return_value=True),
        patch(
            "custom_components.birdweather.coordinator.BirdWeatherClient",
            return_value=client,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_entry_setup_creates_entities_with_states(hass: HomeAssistant) -> None:
    entry = await _setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data, BirdWeatherCoordinator)

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    # 15 sensors + 1 binary sensor; no hardware suites in this poll.
    assert sum(e.domain == "sensor" for e in entities) == 15
    assert sum(e.domain == "binary_sensor" for e in entities) == 1

    def _state(suffix: str) -> str:
        uid = f"{STATION_ID}_{suffix}"
        ent = next(e for e in entities if e.unique_id == uid)
        return hass.states.get(ent.entity_id).state

    assert _state("recent_detections") == "2"   # Robin + Cardinal in the last hour
    assert _state("last_detection") == "American Robin"
    assert _state("daily_count") == "142"        # today_total from the overview
    assert _state("lifetime_species") == "57"
    assert _state("peak_activity_hour") == "07:00"  # hour 7 rendered as a time
    # The timestamp sensor parses the tz-aware ISO into a normalised UTC instant.
    assert _state("history_start") == "2024-01-01T13:30:00+00:00"
    # 24h list is non-empty → extended-silence problem sensor is off.
    assert _state("extended_silence") == "off"

    # Both platforms share one device with a configuration_url back to the
    # station page. No serial_number — a station ID isn't a serial number, and
    # HA would label it "Serial number" on the device page.
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, STATION_ID)})
    assert device is not None
    assert device.serial_number is None
    assert device.configuration_url == f"https://app.birdweather.com/stations/{STATION_ID}"


async def test_entry_setup_creates_puc_hardware_entities(hass: HomeAssistant) -> None:
    entry = await _setup_entry(hass, sensors=_PUC_SENSORS)
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)

    uids = {e.unique_id for e in entities}
    # environment(6) + light(1) + system(4) hardware sensors are added.
    assert f"{STATION_ID}_temperature" in uids
    assert f"{STATION_ID}_light_level" in uids
    assert f"{STATION_ID}_battery_voltage" in uids
    assert sum(e.domain == "sensor" for e in entities) == 15 + 11

    temp = next(e for e in entities if e.unique_id == f"{STATION_ID}_temperature")
    assert hass.states.get(temp.entity_id).state == "21.5"


async def test_unload_entry(hass: HomeAssistant) -> None:
    entry = await _setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_remove_entry_cleans_storage(hass: HomeAssistant, hass_storage) -> None:
    # PHACC mocks Store I/O in-memory via hass_storage, so assert on that.
    entry = await _setup_entry(hass)
    prefix = f"{DOMAIN}.{STATION_ID}."
    assert [k for k in hass_storage if k.startswith(prefix)]  # stores persisted

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    # async_remove_entry deleted this station's per-station .storage files.
    assert not [k for k in hass_storage if k.startswith(prefix)]
