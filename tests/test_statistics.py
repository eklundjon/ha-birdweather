"""Tests for the long-term-statistics backfill."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant

from custom_components.birdweather.statistics import async_import_history_statistics

_ADD = "homeassistant.components.recorder.statistics.async_add_external_statistics"


async def test_builds_cumulative_sum_and_daily_mean(hass: HomeAssistant) -> None:
    client = AsyncMock()
    client.get_daily_history = AsyncMock(return_value=[
        {"date": "2026-06-02", "total": 5, "species": 2},   # out of order on purpose
        {"date": "2026-06-01", "total": 10, "species": 3},
    ])
    with patch(_ADD) as add:
        await async_import_history_statistics(
            hass, client, "12345", "Backyard",
            date(2026, 6, 2), "2026-06-01T00:00:00-05:00",
        )

    assert add.call_count == 2
    det_meta, det_stats = add.call_args_list[0].args[1], add.call_args_list[0].args[2]
    sp_meta, sp_stats = add.call_args_list[1].args[1], add.call_args_list[1].args[2]

    # Detections: a cumulative sum, oldest day first.
    assert det_meta["statistic_id"] == "birdweather:station_12345_daily_detections"
    assert det_meta["has_sum"] is True
    assert [s["state"] for s in det_stats] == [10.0, 5.0]
    assert [s["sum"] for s in det_stats] == [10.0, 15.0]

    # Species richness: a daily mean.
    assert sp_meta["statistic_id"] == "birdweather:station_12345_daily_species"
    assert [s["mean"] for s in sp_stats] == [3.0, 2.0]


async def test_bad_earliest_is_noop(hass: HomeAssistant) -> None:
    client = AsyncMock()
    client.get_daily_history = AsyncMock()
    with patch(_ADD) as add:
        await async_import_history_statistics(
            hass, client, "1", "X", date(2026, 6, 2), "not-a-date"
        )
    add.assert_not_called()
    client.get_daily_history.assert_not_awaited()  # bails before any fetch


async def test_empty_history_is_noop(hass: HomeAssistant) -> None:
    client = AsyncMock()
    client.get_daily_history = AsyncMock(return_value=[])
    with patch(_ADD) as add:
        await async_import_history_statistics(
            hass, client, "1", "X", date(2026, 6, 2), "2026-06-01T00:00:00Z"
        )
    add.assert_not_called()
