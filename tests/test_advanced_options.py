"""The Advanced options knobs are honored by the coordinator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.birdweather.const import (
    CONF_NEW_SPECIES_WINDOW_DAYS,
    CONF_RARITY_PERIOD_MONTHS,
    CONF_RECENT_WINDOW_HOURS,
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    DOMAIN,
)
from custom_components.birdweather.coordinator import BirdWeatherCoordinator

from .coordinator_helpers import make_client, make_coordinator

_BASELINE = [{"bird": "American Robin", "count": 100}]


def _iso(minutes_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00"
    )


def _raw(cn, sp, minutes_ago):
    return {"cn": cn, "sn": f"{cn} sci", "spCode": sp, "dt": _iso(minutes_ago),
            "image": "i.jpg", "audio": None, "confidence": 0.9}


# ---- scan_interval -> update_interval (read in __init__) -------------------- #


def _real_entry(hass: HomeAssistant, **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="12345",
        data={CONF_STATION_ID: "12345", CONF_STATION_NAME: "X"},
        options=options,
    )
    entry.add_to_hass(hass)
    return entry


async def test_scan_interval_sets_update_interval(hass: HomeAssistant) -> None:
    coord = BirdWeatherCoordinator(hass, _real_entry(hass, **{CONF_SCAN_INTERVAL: 15}))
    assert coord.update_interval == timedelta(minutes=15)


async def test_scan_interval_defaults_to_ten_minutes(hass: HomeAssistant) -> None:
    coord = BirdWeatherCoordinator(hass, _real_entry(hass))
    assert coord.update_interval == timedelta(minutes=10)


# ---- recent / rarity / new-species windows (read in the poll) -------------- #


async def test_recent_window_option_widens_recent_set() -> None:
    dets = {"detections": [
        _raw("American Robin", "amerob", 30),   # always recent
        _raw("Barred Owl", "brdowl", 300),      # 5h ago — only inside a wide window
    ]}
    # Default 1h window would exclude the owl; an 8h window includes it.
    coord = make_coordinator(
        client=make_client(baseline=_BASELINE, detections=dets),
        options={CONF_RECENT_WINDOW_HOURS: 8},
    )
    data = await coord._async_update_data()
    assert "Barred Owl" in {d["species"] for d in data["recent_detections"]}


async def test_rarity_period_months_passed_to_client() -> None:
    client = make_client(baseline=_BASELINE, detections={"detections": []})
    coord = make_coordinator(client=client, options={CONF_RARITY_PERIOD_MONTHS: 6})
    await coord._async_update_data()
    client.get_baseline_count.assert_awaited_once_with(coord.station_id, months=6)


async def test_new_species_window_days_affects_overview_cutoff() -> None:
    client = make_client(baseline=_BASELINE, detections={"detections": []})
    coord = make_coordinator(client=client, options={CONF_NEW_SPECIES_WINDOW_DAYS: 7})
    await coord._async_update_data()
    today = datetime.now(UTC).date()
    assert client.get_overview.await_args.kwargs["new_species_cutoff"] == (
        today - timedelta(days=7)
    )
