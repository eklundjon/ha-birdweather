"""Prove the (unmodified) Haikubox coordinator pipeline digests live
BirdWeather data fed through the client's pipeline-contract adapter.

Imports the pure helper functions straight from ha-haikubox and runs them
exactly as the coordinator's _async_update_data would. Requires a sibling
ha-haikubox checkout and the HA venv (the helpers live in a module that
imports homeassistant).

Run:  python scripts/pipeline_smoke.py [station_id]
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

import aiohttp

sys.path.insert(0, "/Users/eklundj/ha-birdweather/custom_components/birdweather")
sys.path.insert(0, "/Users/eklundj/ha-haikubox")

from client import BirdWeatherClient  # noqa: E402
from custom_components.haikubox.coordinator import (  # noqa: E402
    _apply_notability_scores,
    _apply_rarity_scores,
    _build_recent_events,
    _filter_by_dt,
    _normalise_detections,
    _process_yearly_count,
)

RECENT_WINDOW_HOURS = 1
NOTABILITY_WINDOW_HOURS = 24


async def main(station_id: str) -> None:
    async with aiohttp.ClientSession() as session:
        bw = BirdWeatherClient(session)
        raw = await bw.get_raw_detections(station_id, first=300)
        baseline = await bw.get_yearly_count(station_id, months=1, limit=200)

    n_raw = len(raw["detections"])
    with_image = sum(1 for d in raw["detections"] if d.get("image"))
    with_audio = sum(1 for d in raw["detections"] if d.get("audio"))
    print(f"raw events: {n_raw}  (image={with_image}, audio={with_audio})")

    # --- exactly what the coordinator does ---
    ranks, sp_count, _items = _process_yearly_count(baseline)
    print(f"rarity baseline: {sp_count} species ranked")

    daily = sorted(_normalise_detections(raw), key=lambda x: x.get("count", 0), reverse=True)
    _apply_rarity_scores(daily, ranks, sp_count)

    now = datetime.now(timezone.utc)
    recent_raw = {"detections": _filter_by_dt(raw, now - timedelta(hours=RECENT_WINDOW_HOURS))}
    recent = _normalise_detections(recent_raw)
    _apply_rarity_scores(recent, ranks, sp_count)

    _apply_notability_scores(daily, now, NOTABILITY_WINDOW_HOURS, 0.7)
    notable = sorted(daily, key=lambda x: x.get("notability_score", 0), reverse=True)
    rarest = sorted(daily, key=lambda x: x.get("rarity_score", 0), reverse=True)
    events = _build_recent_events(raw, ranks, sp_count, lambda _c: "", 50)

    print(f"\nper-species (24h-ish window): {len(daily)}   recent (1h): {len(recent)}   "
          f"recent_events: {len(events)}")

    print("\n== top notable (rarity-weighted) ==")
    for d in notable[:5]:
        print(f"  {d['species']:24} count={d['count']:3} rarity={d['rarity_score']:.3f} "
              f"notability={d['notability_score']:.3f} rank={d['yearly_rank']}")

    print("\n== rarest (this station) ==")
    for d in rarest[:5]:
        print(f"  {d['species']:24} rarity={d['rarity_score']:.3f} rank={d['yearly_rank']}")

    print("\n== most-recent events ==")
    for e in events[:5]:
        print(f"  {e['last_seen']}  {e['species']:22} rarity={e['rarity_score']:.3f}")


if __name__ == "__main__":
    station = sys.argv[1] if len(sys.argv) > 1 else "20184"
    asyncio.run(main(station))
