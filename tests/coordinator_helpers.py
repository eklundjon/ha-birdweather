"""Helpers for building a BirdWeatherCoordinator in unit tests.

The coordinator does the real work, but its __init__ wires up an aiohttp
session, ten Store objects and the DataUpdateCoordinator base. For unit tests we
bypass __init__ (via __new__) and set just the attributes the poll touches —
the same approach scripts/coordinator_smoke.py uses to drive
_async_update_data deterministically, but with a stubbed client (no network).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from custom_components.birdweather.coordinator import BirdWeatherCoordinator

_STORE_ATTRS = (
    "_store",
    "_last_seen_store",
    "_yearly_store",
    "_seven_day_store",
    "_events_store",
    "_meta_store",
)


class FakeStore:
    """A Store that loads nothing and silently accepts saves."""

    async def async_load(self) -> Any:
        return None

    async def async_save(self, data: Any) -> None:
        return None


def make_client(
    *,
    baseline: list[dict[str, Any]] | None = None,
    detections: dict[str, Any] | None = None,
    overview: dict[str, Any] | None = None,
    time_of_day: dict[str, Any] | None = None,
    sensors: dict[str, Any] | None = None,
) -> AsyncMock:
    """An AsyncMock BirdWeatherClient with canned poll responses."""
    client = AsyncMock()
    client.get_baseline_count = AsyncMock(
        return_value=baseline if baseline is not None else [{"bird": "American Robin", "count": 100}]
    )
    client.get_raw_detections = AsyncMock(
        return_value=detections if detections is not None else {"detections": []}
    )
    client.get_overview = AsyncMock(return_value=overview if overview is not None else {})
    client.get_time_of_day = AsyncMock(
        return_value=time_of_day if time_of_day is not None else {"by_species": {}, "station": []}
    )
    client.get_sensors = AsyncMock(return_value=sensors if sensors is not None else {})
    return client


def make_coordinator(
    hass=None, *, client: AsyncMock | None = None, options: dict | None = None, **attrs
):
    """Build a coordinator via __new__ with deterministic fakes and a stub client."""
    c = BirdWeatherCoordinator.__new__(BirdWeatherCoordinator)
    c.hass = hass
    c.station_id = "12345"
    c.device_name = "Test Station"
    c.config_entry = SimpleNamespace(options=options or {})
    c._client = client or make_client()

    c._baseline_ranks = {}
    c._baseline_species_count = 0
    c._baseline_fetched_date = None
    c._baseline_items = []
    c._diel_by_species = {}
    c._diel_station = []
    c._diel_fetched_date = None
    c._stats_imported_date = None
    c._event_buffer = []
    c._seen_species = {}
    c._sp_codes = {}
    c._sci_names = {}
    c._last_seen = {}
    c._image_urls = {}
    c._image_attr = {}
    c._links_cache = {}
    c._baseline_items = []
    c._seven_day_data = {}
    c._prev_recent_species = None
    for attr in _STORE_ATTRS:
        setattr(c, attr, FakeStore())
    for key, value in attrs.items():
        setattr(c, key, value)
    return c
