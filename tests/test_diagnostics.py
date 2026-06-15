"""Tests for diagnostics redaction."""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.birdweather.const import (
    CONF_STATION_ID,
    CONF_STATION_NAME,
    DOMAIN,
)
from custom_components.birdweather.diagnostics import (
    async_get_config_entry_diagnostics,
)

STATION_ID = "12345"


async def test_diagnostics_redacts_station_identity(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=STATION_ID,
        title="Backyard",
        data={CONF_STATION_ID: STATION_ID, CONF_STATION_NAME: "Backyard"},
        options={"audio_enabled": True},
    )
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(
        last_update_success=True,
        update_interval=timedelta(minutes=10),
        baseline_species_count=42,
        baseline_fetched_date=date(2026, 6, 15),
        lifetime_species_count=87,
        data={"recent_detections": []},
    )

    diag = await async_get_config_entry_diagnostics(hass, entry)

    # The station id must not survive anywhere in the dump.
    assert STATION_ID not in json.dumps(diag, default=str)
    e = diag["entry"]
    assert e["data"][CONF_STATION_ID] == "**REDACTED**"
    assert e["data"][CONF_STATION_NAME] == "**REDACTED**"
    assert e["unique_id"] == "**REDACTED**"
    assert e["title"] == "**REDACTED**"
    # Non-sensitive options pass through.
    assert e["options"] == {"audio_enabled": True}

    # Coordinator summary + data are included.
    coord = diag["coordinator"]
    assert coord["last_update_success"] is True
    assert coord["baseline_species_count"] == 42
    assert coord["baseline_fetched_date"] == "2026-06-15"
    assert coord["lifetime_species_count"] == 87
    assert diag["data"] == {"recent_detections": []}


async def test_diagnostics_handles_unfetched_baseline(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=STATION_ID,
        title="Backyard",
        data={CONF_STATION_ID: STATION_ID, CONF_STATION_NAME: "Backyard"},
    )
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(
        last_update_success=False,
        update_interval=timedelta(minutes=10),
        baseline_species_count=0,
        baseline_fetched_date=None,
        lifetime_species_count=0,
        data=None,
    )

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["coordinator"]["baseline_fetched_date"] is None
