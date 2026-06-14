"""Tests for the coordinator's automation events and store rehydration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.birdweather.const import (
    CONF_ABSENCE_DAYS,
    CONF_ALERT_MIN_CONFIDENCE,
    CONF_WATCHED_EXTRA,
    DOMAIN,
    EVENT_BIRDWEATHER,
)

from .coordinator_helpers import make_client, make_coordinator


def _iso(minutes_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00"
    )


def _raw(*, cn, sp, minutes_ago, confidence=0.9):
    return {
        "cn": cn, "sn": f"{cn} sci", "spCode": sp, "dt": _iso(minutes_ago),
        "image": "i.jpg", "audio": None, "confidence": confidence,
    }


_BASELINE = [{"bird": "American Robin", "count": 500}, {"bird": "Barred Owl", "count": 5}]


def _register_device(hass: HomeAssistant) -> str:
    """Register a device the coordinator's _fire_event can resolve, return id."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain=DOMAIN, unique_id="12345")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "12345")},
    )
    return device.id


def _capture(hass: HomeAssistant) -> list:
    events: list = []
    hass.bus.async_listen(EVENT_BIRDWEATHER, lambda e: events.append(e))
    return events


async def test_new_species_event_fires(hass: HomeAssistant) -> None:
    _register_device(hass)
    events = _capture(hass)

    dets = {"detections": [_raw(cn="Barred Owl", sp="brdowl", minutes_ago=20)]}
    coord = make_coordinator(
        hass=hass,
        client=make_client(baseline=_BASELINE, detections=dets),
        # Pre-seed seen-species (non-empty → skips the silent bootstrap) without
        # the owl, and baseline the recent set so the owl reads as newly seen.
        _seen_species={"American Robin": _iso(9999)},
        _prev_recent_species={"American Robin"},
    )
    await coord._async_update_data()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["type"] == "new_species"
    assert events[0].data["species"] == "Barred Owl"
    # new_species carries the lifetime count (the blueprints read it): the
    # pre-seeded robin plus the owl just recorded this poll.
    assert events[0].data["lifetime_species_count"] == 2


async def test_watched_species_event_fires(hass: HomeAssistant) -> None:
    _register_device(hass)
    events = _capture(hass)

    dets = {"detections": [
        _raw(cn="American Robin", sp="amerob", minutes_ago=10),
        _raw(cn="Barred Owl", sp="brdowl", minutes_ago=15),
    ]}
    coord = make_coordinator(
        hass=hass,
        client=make_client(baseline=_BASELINE, detections=dets),
        options={CONF_WATCHED_EXTRA: "Barred Owl"},
        # Owl already seen (so it's not a new_species), absent from prev recent.
        _seen_species={"American Robin": _iso(9999), "Barred Owl": _iso(9999)},
        _prev_recent_species={"American Robin"},
    )
    await coord._async_update_data()
    await hass.async_block_till_done()

    types = {e.data["type"] for e in events}
    assert types == {"watched_species"}
    assert events[0].data["species"] == "Barred Owl"


async def test_unusual_visitor_event_fires(hass: HomeAssistant) -> None:
    _register_device(hass)
    events = _capture(hass)

    dets = {"detections": [
        _raw(cn="American Robin", sp="amerob", minutes_ago=10),
        _raw(cn="Barred Owl", sp="brdowl", minutes_ago=15),
    ]}
    coord = make_coordinator(
        hass=hass,
        client=make_client(baseline=_BASELINE, detections=dets),
        options={CONF_ABSENCE_DAYS: 30},
        _seen_species={"American Robin": _iso(9999), "Barred Owl": _iso(9999)},
        # Owl last heard 40 days ago → reappearance exceeds the 30-day threshold.
        _last_seen={"Barred Owl": _iso(40 * 24 * 60)},
        _prev_recent_species={"American Robin"},
    )
    await coord._async_update_data()
    await hass.async_block_till_done()

    unusual = [e for e in events if e.data["type"] == "unusual_visitor"]
    assert len(unusual) == 1
    assert unusual[0].data["species"] == "Barred Owl"
    assert unusual[0].data["days_absent"] >= 30


async def test_alert_confidence_gate_suppresses_event(hass: HomeAssistant) -> None:
    _register_device(hass)
    events = _capture(hass)

    dets = {"detections": [_raw(cn="Barred Owl", sp="brdowl", minutes_ago=20, confidence=0.4)]}
    coord = make_coordinator(
        hass=hass,
        client=make_client(baseline=_BASELINE, detections=dets),
        options={CONF_ALERT_MIN_CONFIDENCE: 80},  # owl at 0.4 is below the bar
        _seen_species={"American Robin": _iso(9999)},
        _prev_recent_species={"American Robin"},
    )
    await coord._async_update_data()
    await hass.async_block_till_done()
    assert events == []


async def test_first_poll_is_silent(hass: HomeAssistant) -> None:
    """A fresh poll (prev recent None, empty seen) bootstraps without firing."""
    _register_device(hass)
    events = _capture(hass)

    dets = {"detections": [_raw(cn="Barred Owl", sp="brdowl", minutes_ago=20)]}
    coord = make_coordinator(
        hass=hass, client=make_client(baseline=_BASELINE, detections=dets)
    )
    await coord._async_update_data()
    await hass.async_block_till_done()
    assert events == []
    # The recent set is baselined for the next poll's edge detection.
    assert coord._prev_recent_species == {"Barred Owl"}


# ---- _load_stores ---------------------------------------------------------- #


async def test_load_stores_rehydrates_state() -> None:
    coord = make_coordinator(_stores_loaded=False)
    coord._store.async_load = _const({"American Robin": "2024-01-01T00:00:00Z"})
    coord._yearly_store.async_load = _const(
        [{"species": "American Robin", "rank": 1}, {"species": "Barred Owl", "rank": 2}]
    )
    coord._sticky_store.async_load = _const(
        {"last_detected": {"species": "Barred Owl"}, "last_notable": {"species": "Barred Owl"}}
    )

    await coord._load_stores()

    assert coord._stores_loaded is True
    assert coord._seen_species == {"American Robin": "2024-01-01T00:00:00Z"}
    # Baseline ranks are rebuilt from the persisted yearly items.
    assert coord._baseline_ranks == {"American Robin": 1, "Barred Owl": 2}
    assert coord._baseline_species_count == 2
    assert coord._last_detected == {"species": "Barred Owl"}


async def test_load_stores_tolerates_garbage() -> None:
    coord = make_coordinator(_stores_loaded=False)
    coord._store.async_load = _const("not a dict")
    coord._yearly_store.async_load = _const({"not": "a list"})
    await coord._load_stores()
    assert coord._seen_species == {}
    assert coord._baseline_items == []


def _const(value):
    async def _loader():
        return value
    return _loader
