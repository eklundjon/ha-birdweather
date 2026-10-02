"""Bat support in a full poll: bats come from their own feed and stay out of
every bird figure, and with bat support on they get their own records, sensors'
data and events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.birdweather.const import (
    CONF_ALERT_MIN_CONFIDENCE,
    CONF_WATCHED_SPECIES,
    DOMAIN,
    EVENT_BIRDWEATHER,
)

from .coordinator_helpers import ENTRY_ID, make_client, make_coordinator

STATION = "12345"
# One reference time for every timestamp, so the quiet-gap arithmetic is exact.
_NOW = datetime.now(UTC)


def _iso(minutes_ago: int) -> str:
    return (_NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _bird(cn, sp, minutes_ago):
    return {
        "cn": cn, "sn": f"{cn} sci", "spCode": sp, "dt": _iso(minutes_ago),
        "image": f"{sp}.jpg", "audio": "a.mp3", "confidence": 0.9,
        "ebird_url": f"https://ebird.org/species/{sp}",
        "wikipedia_url": f"https://en.wikipedia.org/wiki/{cn}",
        "birdweather_url": None, "alpha": None, "alpha6": None,
        "classification": "bird",
    }


def _bat(cn, minutes_ago, behavior_code="bat_search_clutter"):
    # Shaped like a real bat-edition PUC's feed: no eBird code, a behavior.
    return {
        "cn": cn, "sn": "Chiroptera", "spCode": "", "dt": _iso(minutes_ago),
        "image": "bats.jpg", "audio": "bat.flac", "confidence": 1.0,
        "ebird_url": None,
        "wikipedia_url": "https://en.wikipedia.org/wiki/Bat",
        "birdweather_url": "https://app.birdweather.com/species/bats",
        "alpha": None, "alpha6": None,
        "classification": "bat",
        "behavior": "Search/Clutter", "behavior_code": behavior_code,
        "behavior_confidence": 0.6,
    }


_BIRDS = [
    _bird("American Robin", "amerob", 30),
    _bird("Northern Cardinal", "norcar", 300),
]
_BATS = [_bat("Bats", 10), _bat("Hoary Bat", 20)]

_OVERVIEW = {
    "today_total": 160, "lifetime_species": 2, "today_top": [],
    "bat_today_total": 37,
    "bat_today_top": [
        {"species": "Bats", "count": 35, "classification": "bat", "image_url": "bats.jpg",
         "sp_code": "", "scientific_name": "Chiroptera"},
        {"species": "Hoary Bat", "count": 2, "classification": "bat", "image_url": "hoary.jpg",
         "sp_code": "", "scientific_name": "Lasiurus cinereus"},
    ],
}


def _client(bats=None):
    """A client whose detection feed depends on the class asked for."""
    client = make_client(
        baseline=[{"bird": "American Robin", "count": 500}, {"bird": "Northern Cardinal", "count": 50}],
        overview=_OVERVIEW,
    )
    bat_feed = list(_BATS if bats is None else bats)

    async def feed(station_id, first=300, classifications=None):
        if classifications == ["bat"]:
            return {"detections": [dict(b) for b in bat_feed]}
        assert classifications == ["avian"]
        return {"detections": [dict(b) for b in _BIRDS]}

    client.get_raw_detections = AsyncMock(side_effect=feed)
    return client, bat_feed


@pytest.fixture
def events(hass: HomeAssistant) -> list:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=STATION, entry_id=ENTRY_ID)
    entry.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, STATION)}
    )
    captured: list = []
    hass.bus.async_listen(EVENT_BIRDWEATHER, lambda e: captured.append(e.data))
    return captured


def _coordinator(hass, *, bat_support, options=None, bats=None):
    client, bat_feed = _client(bats)
    c = make_coordinator(hass, client=client, options=options or {}, _bat_support=bat_support)
    return c, client, bat_feed


def _species(records) -> set[str]:
    return {r["species"] for r in records or []}


async def test_bats_not_fetched_without_bat_support(hass: HomeAssistant, events) -> None:
    c, client, _ = _coordinator(hass, bat_support=False)
    data = await c._async_update_data()

    asked = [call.kwargs.get("classifications") for call in client.get_raw_detections.await_args_list]
    assert asked == [["avian"]]
    assert data["last_detection"]["species"] == "American Robin"
    assert data["bats_today"] == []
    assert data["bat_today_total"] == 0
    assert not {"Bats", "Hoary Bat"} & set(c._seen_species)


async def test_bat_support_adds_bat_data(hass: HomeAssistant, events) -> None:
    c, _, _ = _coordinator(hass, bat_support=True)
    data = await c._async_update_data()

    # Bird figures stay birds-only.
    for key in ("recent_detections", "detections_24h", "notable_detections",
                "rarest_species", "new_detections"):
        assert not _species(data[key]) & {"Bats", "Hoary Bat"}, key
    assert c.lifetime_species_count == 2

    # last_detection is whatever was heard last; the per-class records split it.
    assert data["last_detection"]["species"] == "Bats"
    assert data["last_detection"]["classification"] == "bat"
    assert data["last_bird_detection"]["species"] == "American Robin"
    bat = data["last_bat_detection"]
    assert bat["species"] == "Bats"
    assert bat["behavior_code"] == "bat_search_clutter"
    assert bat["behavior_confidence"] == 0.6

    # Bats have only Wikipedia and BirdWeather links, and no audio.
    assert bat["ebird_url"] is None
    assert bat["allaboutbirds_url"] is None
    assert bat["macaulay_url"] is None
    assert bat["wikipedia_url"] == "https://en.wikipedia.org/wiki/Bat"
    assert bat["birdweather_url"] == "https://app.birdweather.com/species/bats"
    assert bat["audio_url"] is None
    assert data["last_bird_detection"]["ebird_url"]

    # The 24-hour bat list from the native bat counts, with each bat's behavior.
    assert [(r["species"], r["count"]) for r in data["bats_today"]] == [
        ("Bats", 35), ("Hoary Bat", 2),
    ]
    assert data["bats_today"][0]["behavior_code"] == "bat_search_clutter"
    assert data["bat_today_total"] == 37

    # Bats are in the first-seen log and watch-list picker, as bats.
    assert {"Bats", "Hoary Bat"} <= set(c._seen_species)
    assert {"Bats", "Hoary Bat"} <= set(c.known_species)

    # The first poll establishes baselines without firing anything.
    await hass.async_block_till_done()
    assert events == []


async def test_new_bat_species_fires_new_species(hass: HomeAssistant, events) -> None:
    c, _, bat_feed = _coordinator(hass, bat_support=True)
    await c._async_update_data()

    bat_feed.append(_bat("Pallid Bat", 5, behavior_code="bat_feeding_buzz"))
    await c._async_update_data()
    await hass.async_block_till_done()

    fired = [e for e in events if e["type"] == "new_species"]
    assert [e["species"] for e in fired] == ["Pallid Bat"]
    assert fired[0]["classification"] == "bat"
    assert fired[0]["behavior_code"] == "bat_feeding_buzz"
    assert fired[0]["lifetime_species_count"] == 3  # bat species, not birds
    assert fired[0]["ebird_url"] is None
    assert fired[0]["wikipedia_url"] == "https://en.wikipedia.org/wiki/Bat"


async def test_watched_bat_fires_watched_species(hass: HomeAssistant, events) -> None:
    c, _, _ = _coordinator(hass, bat_support=True, options={CONF_WATCHED_SPECIES: ["Hoary Bat"]})
    c._prev_recent_bats = set()  # not the first poll of the session
    await c._async_update_data()
    await hass.async_block_till_done()

    assert [e["species"] for e in events if e["type"] == "watched_species"] == ["Hoary Bat"]


@pytest.mark.parametrize(
    ("prior_minutes_ago", "fires"),
    [
        (240, True),   # bats return after nearly four quiet hours
        (45, False),   # the previous bat was only 25 minutes before these
        (None, False), # no previous bat: this poll only sets the baseline
    ],
)
async def test_bat_activity(hass: HomeAssistant, events, prior_minutes_ago, fires) -> None:
    c, _, _ = _coordinator(hass, bat_support=True)
    if prior_minutes_ago is not None:
        c._last_by_class["bat"] = {
            "species": "Bats", "classification": "bat", "last_seen": _iso(prior_minutes_ago),
        }
    await c._async_update_data()
    await hass.async_block_till_done()

    activity = [e for e in events if e["type"] == "bat_activity"]
    if not fires:
        assert activity == []
        return
    assert len(activity) == 1
    assert activity[0]["species"] == "Bats"  # the newest bat
    assert activity[0]["count"] == 2
    assert activity[0]["quiet_minutes"] == prior_minutes_ago - 20
    assert activity[0]["behavior_code"] == "bat_search_clutter"


async def test_alert_confidence_gates_bat_events(hass: HomeAssistant, events) -> None:
    c, _, bat_feed = _coordinator(hass, bat_support=True, options={CONF_ALERT_MIN_CONFIDENCE: 99})
    await c._async_update_data()
    low = _bat("Pallid Bat", 5)
    low["confidence"] = 0.5
    bat_feed.append(low)
    await c._async_update_data()
    await hass.async_block_till_done()

    assert [e for e in events if e["type"] == "new_species"] == []


async def test_bat_feed_failure_keeps_the_poll(hass: HomeAssistant, events) -> None:
    """The bat feed is best-effort: a failure doesn't cost the bird data."""
    from custom_components.birdweather.client import BirdWeatherError

    c, client, _ = _coordinator(hass, bat_support=True)
    birds_only = client.get_raw_detections.side_effect

    async def flaky(station_id, first=300, classifications=None):
        if classifications == ["bat"]:
            raise BirdWeatherError("bat feed down")
        return await birds_only(station_id, first, classifications)

    client.get_raw_detections.side_effect = flaky
    data = await c._async_update_data()
    assert data["last_detection"]["species"] == "American Robin"
    assert data["last_bat_detection"] is None
