"""Run the coordinator's bird pipeline over live BirdWeather data and print a
readable digest: rarity baseline, notable and rarest species, recent events.

Calls the real client and the pure normalize helpers in the same order, with
the same defaults, as BirdWeatherCoordinator._async_update_data, but with no
coordinator, stores, or HA state. Use it to eyeball what a pipeline change does
to real data; coordinator_smoke.py covers the full coordinator end to end.
Needs the HA venv (importing the package imports homeassistant).

Run:  python scripts/pipeline_smoke.py [station_id]
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiohttp

# Repo root on the path so the integration imports as a package. Putting the
# birdweather package dir itself on the path would let its statistics.py shadow
# the stdlib module.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.birdweather.client import (  # noqa: E402
    API_BIRDS,
    BirdWeatherClient,
)
from custom_components.birdweather.const import (  # noqa: E402
    DAILY_WINDOW_HOURS,
    DEFAULT_NOTABLE_RARITY_WEIGHT,
    DETECTION_FETCH_LIMIT,
    LAST_DETECTION_EVENT_LIMIT,
    NOTABILITY_WINDOW_HOURS,
    RARITY_PERIOD_MONTHS,
    RECENT_WINDOW_HOURS,
)
from custom_components.birdweather.normalize import (  # noqa: E402
    _apply_notability_scores,
    _apply_rarity_scores,
    _build_recent_events,
    _filter_by_dt,
    _normalise_detections,
    _process_baseline_count,
)


async def main(station_id: str) -> None:
    async with aiohttp.ClientSession() as session:
        bw = BirdWeatherClient(session)
        baseline = await bw.get_baseline_count(station_id, months=RARITY_PERIOD_MONTHS)
        raw = await bw.get_raw_detections(
            station_id, first=DETECTION_FETCH_LIMIT, classifications=[API_BIRDS]
        )

    n_raw = len(raw["detections"])
    with_image = sum(1 for d in raw["detections"] if d.get("image"))
    with_audio = sum(1 for d in raw["detections"] if d.get("audio"))
    print(f"raw events: {n_raw}  (image={with_image}, audio={with_audio})")

    ranks, sp_count, _items = _process_baseline_count(baseline)
    print(f"rarity baseline: {sp_count} species ranked over {RARITY_PERIOD_MONTHS} month(s)")

    now = datetime.now(UTC)
    daily_raw = {"detections": _filter_by_dt(raw, now - timedelta(hours=DAILY_WINDOW_HOURS))}
    recent_raw = {
        "detections": _filter_by_dt(daily_raw, now - timedelta(hours=RECENT_WINDOW_HOURS))
    }

    recent = _normalise_detections(recent_raw)
    _apply_rarity_scores(recent, ranks, sp_count)
    daily = sorted(_normalise_detections(daily_raw), key=lambda x: x.get("count", 0), reverse=True)
    _apply_rarity_scores(daily, ranks, sp_count)

    _apply_notability_scores(
        daily, now, NOTABILITY_WINDOW_HOURS, DEFAULT_NOTABLE_RARITY_WEIGHT / 100.0
    )
    notable = sorted(daily, key=lambda x: x.get("notability_score", 0), reverse=True)
    rarest = sorted(daily, key=lambda x: x.get("rarity_score", 0), reverse=True)
    events = _build_recent_events(
        daily_raw, ranks, sp_count, lambda _c: None, LAST_DETECTION_EVENT_LIMIT
    )

    print(
        f"\nper-species ({DAILY_WINDOW_HOURS}h): {len(daily)}   "
        f"recent ({RECENT_WINDOW_HOURS}h): {len(recent)}   recent_events: {len(events)}"
    )

    print("\n== top notable (rarity-weighted) ==")
    for d in notable[:5]:
        print(
            f"  {d['species']:24} count={d['count']:3} rarity={d['rarity_score']:.3f} "
            f"notability={d['notability_score']:.3f} rank={d['yearly_rank']}"
        )

    print("\n== rarest (this station) ==")
    for d in rarest[:5]:
        print(f"  {d['species']:24} rarity={d['rarity_score']:.3f} rank={d['yearly_rank']}")

    print("\n== most-recent events ==")
    for e in events[:5]:
        print(f"  {e['last_seen']}  {e['species']:22} rarity={e['rarity_score']:.3f}")


if __name__ == "__main__":
    station = sys.argv[1] if len(sys.argv) > 1 else "20184"
    asyncio.run(main(station))
