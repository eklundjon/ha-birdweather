"""Exercise the BirdWeather client against the live public API (no auth).

Run:  python scripts/smoke.py [lat] [lon]
Defaults to a point in upstate NY (near a known PUC station).
"""

import asyncio
import sys

import aiohttp

sys.path.insert(0, "custom_components/birdweather")
from client import BirdWeatherClient  # noqa: E402


async def main(lat: float, lon: float) -> None:
    async with aiohttp.ClientSession() as session:
        bw = BirdWeatherClient(session)

        print(f"== nearby_stations({lat}, {lon}, 50km) ==")
        stations = await bw.nearby_stations(lat, lon, radius_km=50, first=5)
        for s in stations:
            d = s["distance_km"]
            print(f"  [{s['id']:>6}] {s['name'][:30]:30} {s['state']:14} "
                  f"{d:.1f} km" if d is not None else f"  [{s['id']}] {s['name']}")
        if not stations:
            print("  (none nearby)")
            return

        sid = stations[0]["id"]
        print(f"\n== get_detections(station {sid}, first=3) ==")
        for det in await bw.get_detections(sid, first=3):
            print(f"  {det['last_seen']}  {det['species']:22} "
                  f"conf={det['confidence']:.2f} {det['certainty']}")
            print(f"      img={bool(det['image_url'])} audio={bool(det['audio_url'])} "
                  f"ebird={det['sp_code']}")

        print(f"\n== get_species_counts(station {sid}, 1 month) ==")
        counts = await bw.get_species_counts(sid, months=1, limit=8)
        for sci, n in sorted(counts.items(), key=lambda kv: -kv[1])[:8]:
            print(f"  {n:5}  {sci}")


if __name__ == "__main__":
    lat = float(sys.argv[1]) if len(sys.argv) > 1 else 42.7256
    lon = float(sys.argv[2]) if len(sys.argv) > 2 else -73.4205
    asyncio.run(main(lat, lon))
