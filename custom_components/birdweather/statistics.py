"""Long-term-statistics backfill for the BirdWeather integration.

Imports the station's true daily history into Home Assistant's recorder
statistics: detections/day (a cumulative `sum` → the Statistics card shows totals
per day/week/month) and species richness/day (a daily `mean`). Kept out of the
coordinator so the recorder imports stay isolated and lazy.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

from .const import DOMAIN

if TYPE_CHECKING:
    from .client import BirdWeatherClient


async def async_import_history_statistics(
    hass: HomeAssistant,
    client: BirdWeatherClient,
    station_id: str,
    device_name: str,
    today: date,
    earliest_iso: str,
) -> None:
    """Backfill HA long-term statistics with the station's true daily history
    from its first recorded day to today: detection totals (a cumulative `sum`)
    and species richness (a daily `mean`). Re-runs daily and is idempotent on
    (statistic_id, day), so it fills yesterday and corrects late data.

    Full re-import each day keeps the cumulative sum correct without tracking
    state; fine at typical history lengths — a busy multi-year station could
    instead import incrementally via get_last_statistics (TODO)."""
    # Lazy imports: only pull in recorder internals when actually backfilling.
    from homeassistant.components.recorder.models import (  # noqa: PLC0415
        StatisticData,
        StatisticMeanType,
        StatisticMetaData,
    )
    from homeassistant.components.recorder.statistics import (  # noqa: PLC0415
        async_add_external_statistics,
    )
    from homeassistant.util import dt as dt_util  # noqa: PLC0415

    try:
        earliest = datetime.fromisoformat(earliest_iso).date()
    except (TypeError, ValueError):
        return
    history = await client.get_daily_history(station_id, earliest, today)
    if not history:
        return

    det_stats: list[StatisticData] = []
    sp_stats: list[StatisticData] = []
    cumulative = 0.0
    for row in sorted(history, key=lambda r: r["date"]):
        try:
            day = date.fromisoformat(row["date"])
        except (TypeError, ValueError):
            continue
        start = dt_util.start_of_local_day(day)  # local midnight, hour-aligned
        cumulative += row["total"]
        det_stats.append(
            StatisticData(start=start, state=float(row["total"]), sum=cumulative)
        )
        species = float(row["species"])
        sp_stats.append(
            StatisticData(start=start, mean=species, min=species, max=species)
        )
    if not det_stats:
        return

    async_add_external_statistics(
        hass,
        StatisticMetaData(
            has_sum=True,
            has_mean=False,
            mean_type=StatisticMeanType.NONE,
            name=f"{device_name} daily detections",
            source=DOMAIN,
            statistic_id=f"{DOMAIN}:station_{station_id}_daily_detections",
            unit_of_measurement="detections",
            unit_class=None,
        ),
        det_stats,
    )
    async_add_external_statistics(
        hass,
        StatisticMetaData(
            has_sum=False,
            mean_type=StatisticMeanType.ARITHMETIC,
            name=f"{device_name} daily species",
            source=DOMAIN,
            statistic_id=f"{DOMAIN}:station_{station_id}_daily_species",
            unit_of_measurement="species",
            unit_class=None,
        ),
        sp_stats,
    )
