"""Tests for the BirdWeather config and options flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.birdweather.client import BirdWeatherError
from custom_components.birdweather.config_flow import SECTION_ADVANCED
from custom_components.birdweather.const import (
    CONF_ABSENCE_DAYS,
    CONF_ALERT_MIN_CONFIDENCE,
    CONF_AUDIO_ENABLED,
    CONF_FEED_MIN_CONFIDENCE,
    CONF_NEW_SPECIES_WINDOW_DAYS,
    CONF_NOTABLE_RARITY_WEIGHT,
    CONF_RARITY_PERIOD_MONTHS,
    CONF_RECENT_WINDOW_HOURS,
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_WATCHED_EXTRA,
    CONF_WATCHED_SPECIES,
    DOMAIN,
)

STATION_ID = "12345"
_CLIENT = "custom_components.birdweather.config_flow.BirdWeatherClient"
_PATCH_SETUP_ENTRY = "custom_components.birdweather.async_setup_entry"


def _fake_client(**methods) -> object:
    """A BirdWeatherClient stand-in: patch the class so it returns this.

    Defaults give an empty nearby list (so the initial form renders without
    network) and a valid station lookup; override per test.
    """
    client = AsyncMock()
    client.nearby_stations = AsyncMock(return_value=methods.get("nearby", []))
    client.search_stations = AsyncMock(return_value=methods.get("search", []))
    client.get_station = AsyncMock(
        return_value=methods.get("station", {"id": STATION_ID, "name": "Backyard"})
    )
    if "station_exc" in methods:
        client.get_station.side_effect = methods["station_exc"]
    return client


# ---- user flow ------------------------------------------------------------- #


async def test_user_flow_shows_form(hass: HomeAssistant) -> None:
    with patch(_CLIENT, return_value=_fake_client()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_user_flow_selects_station_creates_entry(hass: HomeAssistant) -> None:
    with (
        patch(_CLIENT, return_value=_fake_client()),
        patch(_PATCH_SETUP_ENTRY, return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_STATION_ID: STATION_ID}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Backyard"
    assert result["data"] == {
        CONF_STATION_ID: STATION_ID,
        CONF_STATION_NAME: "Backyard",
    }


async def test_user_flow_invalid_station(hass: HomeAssistant) -> None:
    """A serial the API doesn't recognise (None) surfaces as invalid_station."""
    with patch(_CLIENT, return_value=_fake_client(station=None)):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_STATION_ID: STATION_ID}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_station"}


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """A transport/API failure during lookup surfaces as cannot_connect."""
    with patch(_CLIENT, return_value=_fake_client(station_exc=BirdWeatherError("boom"))):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_STATION_ID: STATION_ID}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_no_selection(hass: HomeAssistant) -> None:
    """Submitting with neither a station nor a search re-renders with an error."""
    with patch(_CLIENT, return_value=_fake_client()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_selection"}


async def test_user_flow_already_configured(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain=DOMAIN, unique_id=STATION_ID, data={CONF_STATION_ID: STATION_ID}
    ).add_to_hass(hass)

    with patch(_CLIENT, return_value=_fake_client()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_STATION_ID: STATION_ID}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ---- options flow ---------------------------------------------------------- #


def _entry(hass: HomeAssistant, **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=STATION_ID,
        data={CONF_STATION_ID: STATION_ID, CONF_STATION_NAME: "Backyard"},
        options=options,
    )
    entry.add_to_hass(hass)
    return entry


async def test_options_flow_saves_values(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_NOTABLE_RARITY_WEIGHT: 80,
            CONF_ABSENCE_DAYS: 20,
            CONF_FEED_MIN_CONFIDENCE: 50,
            CONF_ALERT_MIN_CONFIDENCE: 75,
            CONF_AUDIO_ENABLED: True,
            CONF_WATCHED_SPECIES: [],
            CONF_WATCHED_EXTRA: "Snowy Owl",
            SECTION_ADVANCED: {
                CONF_RECENT_WINDOW_HOURS: 6,
                CONF_SCAN_INTERVAL: 15,
                CONF_RARITY_PERIOD_MONTHS: 3,
                CONF_NEW_SPECIES_WINDOW_DAYS: 14,
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_NOTABLE_RARITY_WEIGHT] == 80
    assert entry.options[CONF_AUDIO_ENABLED] is True
    assert entry.options[CONF_WATCHED_EXTRA] == "Snowy Owl"
    # Advanced section is flattened to top-level options the coordinator reads.
    assert SECTION_ADVANCED not in entry.options
    assert entry.options[CONF_SCAN_INTERVAL] == 15
    assert entry.options[CONF_RECENT_WINDOW_HOURS] == 6
    assert entry.options[CONF_RARITY_PERIOD_MONTHS] == 3
    assert entry.options[CONF_NEW_SPECIES_WINDOW_DAYS] == 14


async def test_options_flow_prefills_saved_values(hass: HomeAssistant) -> None:
    entry = _entry(hass, **{CONF_NOTABLE_RARITY_WEIGHT: 55})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    weight_default = next(
        m.default()
        for m in result["data_schema"].schema
        if getattr(m, "schema", None) == CONF_NOTABLE_RARITY_WEIGHT
    )
    assert weight_default == 55
