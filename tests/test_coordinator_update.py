"""End-to-end tests for BirdWeatherCoordinator._async_update_data.

These drive the real poll method with a stubbed client (no network, no HA) and
assert the output dict the sensors consume — the windowing, scoring, sticky
records, and the new-species bootstrap.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.birdweather.client import BirdWeatherError
from custom_components.birdweather.const import (
    CONF_AUDIO_ENABLED,
    CONF_FEED_MIN_CONFIDENCE,
)
from custom_components.birdweather.coordinator import _UPDATE_FAILED_TAKES_RETRY_AFTER

from .coordinator_helpers import make_client, make_coordinator


def _iso(minutes_ago: int) -> str:
    dt = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _raw(*, cn, sp, minutes_ago, confidence=0.9, image="i.jpg", audio="a.mp3"):
    return {
        "cn": cn, "sn": f"{cn} sci", "spCode": sp, "dt": _iso(minutes_ago),
        "image": image, "audio": audio, "confidence": confidence,
        "ebird_url": f"https://ebird.org/species/{sp}",
        "wikipedia_url": f"https://en.wikipedia.org/wiki/{cn}",
        "birdweather_url": None, "alpha": None, "alpha6": None,
    }


_BASELINE = [
    {"bird": "American Robin", "count": 500},
    {"bird": "Northern Cardinal", "count": 200},
    {"bird": "Barred Owl", "count": 5},
]


def _detections() -> dict:
    return {"detections": [
        _raw(cn="American Robin", sp="amerob", minutes_ago=30),   # recent (<1h) + daily
        _raw(cn="Northern Cardinal", sp="norcar", minutes_ago=45),  # recent + daily
        _raw(cn="Barred Owl", sp="brdowl", minutes_ago=300),      # daily only (5h ago)
    ]}


async def test_poll_produces_full_sensor_dict() -> None:
    client = make_client(baseline=_BASELINE, detections=_detections())
    coord = make_coordinator(client=client)
    data = await coord._async_update_data()

    # All the sensor keys the platform expects are present.
    for key in (
        "recent_detections", "last_detection", "recent_events", "notable_detection",
        "detections_24h", "daily_top_species", "notable_detections",
        "new_detections", "new_detection", "lifetime_species_count",
        "yearly_top_species", "rarest_species", "watched_species", "sensors",
        "hourly_activity", "peak_activity_hour",
    ):
        assert key in data


async def test_recent_vs_daily_windowing() -> None:
    client = make_client(baseline=_BASELINE, detections=_detections())
    coord = make_coordinator(client=client)
    data = await coord._async_update_data()

    # 1-hour recent window excludes the 5h-old owl; 24h window includes it.
    recent = {d["species"] for d in data["recent_detections"]}
    daily = {d["species"] for d in data["detections_24h"]}
    assert recent == {"American Robin", "Northern Cardinal"}
    assert "Barred Owl" in daily


async def test_rarity_scores_applied_from_baseline() -> None:
    client = make_client(baseline=_BASELINE, detections=_detections())
    coord = make_coordinator(client=client)
    data = await coord._async_update_data()

    by_species = {d["species"]: d for d in data["detections_24h"]}
    # Baseline ranks: Robin=1, Cardinal=2, Owl=3 of 3 species → owl is rarest.
    assert by_species["American Robin"]["rarity_score"] == round(1 / 3, 4)
    assert by_species["Barred Owl"]["rarity_score"] == 1.0


async def test_last_detection_is_most_recent() -> None:
    client = make_client(baseline=_BASELINE, detections=_detections())
    coord = make_coordinator(client=client)
    data = await coord._async_update_data()
    # Newest recent detection is the 30-min-old robin.
    assert data["last_detection"]["species"] == "American Robin"


async def test_last_detection_persists_when_feed_empties() -> None:
    """#62: last_detection is backed by a persisted buffer, so it survives an
    outage (empty feed) instead of draining; notable drains with its window."""
    coord = make_coordinator(client=make_client(baseline=_BASELINE, detections=_detections()))
    data = await coord._async_update_data()
    assert data["last_detection"]["species"] == "American Robin"
    assert data["notable_detection"] is not None

    # Next poll: the station has gone silent (feed empty), baseline still cached.
    coord._client = make_client(baseline=_BASELINE, detections={"detections": []})
    data = await coord._async_update_data()
    # last_detection persists from the buffer; recent feed + notable drain.
    assert data["last_detection"]["species"] == "American Robin"
    assert data["recent_events"]  # buffer non-empty
    assert data["recent_detections"] == []
    assert data["notable_detection"] is None
    assert data["notable_detections"] == []


async def test_event_buffer_dedups_and_persists_across_polls() -> None:
    dets = _detections()  # one dict, identical timestamps across both polls
    coord = make_coordinator(client=make_client(baseline=_BASELINE, detections=dets))
    await coord._async_update_data()
    first = len(coord._event_buffer)
    assert first == 3  # robin, cardinal, owl (one event each)

    # Re-poll the identical feed: no new (sp_code, last_seen) keys → no growth.
    coord._client = make_client(baseline=_BASELINE, detections=dets)
    await coord._async_update_data()
    assert len(coord._event_buffer) == first


async def test_seen_species_bootstrap_from_daily_window() -> None:
    client = make_client(baseline=_BASELINE, detections=_detections())
    coord = make_coordinator(client=client)
    data = await coord._async_update_data()
    # Fresh install seeds _seen_species from the full 24h window (all three).
    assert set(coord._seen_species) == {"American Robin", "Northern Cardinal", "Barred Owl"}
    assert data["lifetime_species_count"] == 3


async def test_overview_fields_surfaced() -> None:
    overview = {
        "today_total": 142,
        "typical_daily": 88,
        "new_species_window": 4,
        "history_earliest": "2024-01-01",
        "lifetime_species": 57,
        "today_top": [],
    }
    client = make_client(baseline=_BASELINE, detections=_detections(), overview=overview)
    coord = make_coordinator(client=client)
    data = await coord._async_update_data()
    assert data["today_total"] == 142
    assert data["typical_daily_count"] == 88
    assert data["new_species_window"] == 4
    assert data["history_earliest"] == "2024-01-01"
    # overview lifetime wins over the seen-species count when present.
    assert data["lifetime_species_count"] == 57


async def test_new_station_without_detections_loads() -> None:
    client = make_client(baseline=[], detections={"detections": []})
    coord = make_coordinator(client=client)
    data = await coord._async_update_data()

    assert data["recent_detections"] == []
    assert data["last_detection"] is None
    assert data["lifetime_species_count"] == 0
    assert data["yearly_top_species"] == []
    assert coord.baseline_fetched_date == datetime.now(UTC).date()


async def test_empty_baseline_does_not_hide_incoming_detections() -> None:
    client = make_client(baseline=[], detections=_detections())
    coord = make_coordinator(client=client)
    data = await coord._async_update_data()

    assert data["last_detection"]["species"] == "American Robin"
    assert len(data["detections_24h"]) == 3
    assert data["yearly_top_species"] == []


async def test_failed_initial_baseline_retries_and_recovers() -> None:
    client = make_client(baseline=[], detections={"detections": []})
    client.get_baseline_count.side_effect = BirdWeatherError("unavailable")
    coord = make_coordinator(client=client)

    with pytest.raises(UpdateFailed, match="Rarity baseline not yet available"):
        await coord._async_update_data()
    assert coord.baseline_fetched_date is None

    client.get_baseline_count.side_effect = None
    data = await coord._async_update_data()
    assert data["last_detection"] is None
    assert client.get_baseline_count.await_count == 2


@pytest.mark.parametrize("baseline", [[], _BASELINE])
async def test_failed_baseline_refresh_preserves_cached_data(baseline) -> None:
    client = make_client(baseline=baseline, detections=_detections())
    coord = make_coordinator(client=client)
    before = await coord._async_update_data()
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    coord._baseline_fetched_date = yesterday
    client.get_baseline_count.side_effect = BirdWeatherError("unavailable")

    after = await coord._async_update_data()
    assert after["yearly_top_species"] == before["yearly_top_species"]
    assert after["last_detection"] == before["last_detection"]
    assert coord.baseline_fetched_date == yesterday


async def test_empty_baseline_does_not_mask_detection_feed_failure() -> None:
    client = make_client(baseline=[])
    client.get_raw_detections.side_effect = BirdWeatherError("unavailable")
    coord = make_coordinator(client=client)

    with pytest.raises(UpdateFailed, match="Error communicating with BirdWeather API"):
        await coord._async_update_data()


@pytest.mark.parametrize("cached_baseline", [[], None, {"invalid": "cache"}])
async def test_empty_baseline_cache_survives_restart_during_outage(hass, cached_baseline) -> None:
    client = make_client()
    client.get_baseline_count.side_effect = BirdWeatherError("unavailable")
    coord = make_coordinator(hass=hass, client=client)
    coord._yearly_store.async_load = AsyncMock(return_value=cached_baseline)
    await coord._load_stores()

    if cached_baseline == []:
        data = await coord._async_update_data()
        assert data["yearly_top_species"] == []
    else:
        with pytest.raises(UpdateFailed, match="Rarity baseline not yet available"):
            await coord._async_update_data()


async def test_feed_confidence_filter_drops_low_events() -> None:
    dets = {"detections": [
        _raw(cn="American Robin", sp="amerob", minutes_ago=20, confidence=0.95),
        _raw(cn="Barred Owl", sp="brdowl", minutes_ago=25, confidence=0.30),
    ]}
    client = make_client(baseline=_BASELINE, detections=dets)
    coord = make_coordinator(client=client, options={CONF_FEED_MIN_CONFIDENCE: 50})
    data = await coord._async_update_data()
    recent = {d["species"] for d in data["recent_detections"]}
    assert recent == {"American Robin"}  # low-confidence owl filtered out


async def test_audio_url_gated_by_option() -> None:
    client = make_client(baseline=_BASELINE, detections=_detections())
    # Default (audio disabled) → no audio_url on records.
    coord = make_coordinator(client=client)
    data = await coord._async_update_data()
    assert data["last_detection"]["audio_url"] is None

    client2 = make_client(baseline=_BASELINE, detections=_detections())
    coord2 = make_coordinator(client=client2, options={CONF_AUDIO_ENABLED: True})
    data2 = await coord2._async_update_data()
    assert data2["last_detection"]["audio_url"] == "a.mp3"


async def test_diel_peak_hour_surfaced() -> None:
    hourly = [0] * 24
    hourly[7] = 99
    tod = {"by_species": {}, "station": hourly}
    client = make_client(baseline=_BASELINE, detections=_detections(), time_of_day=tod)
    coord = make_coordinator(client=client)
    data = await coord._async_update_data()
    assert data["peak_activity_hour"] == 7
    assert data["hourly_activity"] == hourly


async def _poll_with_detections_error(err: Exception) -> UpdateFailed:
    client = make_client(detections={"detections": []})
    client.get_raw_detections.side_effect = err
    coord = make_coordinator(client=client)
    coord.update_interval = timedelta(minutes=10)
    with pytest.raises(UpdateFailed) as excinfo:
        await coord._async_update_data()
    return excinfo.value


async def test_rate_limit_delays_next_refresh() -> None:
    """A Retry-After longer than the poll interval sets retry_after (2025.12+)."""
    err = await _poll_with_detections_error(BirdWeatherError("429", retry_after=1800))
    if _UPDATE_FAILED_TAKES_RETRY_AFTER:
        assert err.retry_after == 1800
    else:
        assert getattr(err, "retry_after", None) is None


async def test_short_retry_after_is_ignored() -> None:
    """A Retry-After shorter than the poll interval would poll sooner, so it's dropped."""
    err = await _poll_with_detections_error(BirdWeatherError("429", retry_after=30))
    assert getattr(err, "retry_after", None) is None


async def test_error_without_retry_after_raises_plainly() -> None:
    err = await _poll_with_detections_error(BirdWeatherError("transport error: down"))
    assert getattr(err, "retry_after", None) is None
