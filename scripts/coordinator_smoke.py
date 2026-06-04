"""Drive the real BirdWeatherCoordinator._async_update_data against the live
API, with HA's Store/hass faked out, to confirm the full pipeline produces a
complete sensor data dict. Run with the HA venv.

    python scripts/coordinator_smoke.py [station_id]
"""

import asyncio
import sys

import aiohttp

sys.path.insert(0, ".")
from custom_components.birdweather.client import BirdWeatherClient  # noqa: E402
from custom_components.birdweather.coordinator import BirdWeatherCoordinator  # noqa: E402


class _FakeStore:
    async def async_load(self):
        return None

    async def async_save(self, data):
        return None


class _FakeEntry:
    options: dict = {}


async def main(station_id: str) -> None:
    async with aiohttp.ClientSession() as session:
        coord = BirdWeatherCoordinator.__new__(BirdWeatherCoordinator)
        # Inject just what _async_update_data touches.
        coord.station_id = station_id
        coord.device_name = "Test Station"
        coord._client = BirdWeatherClient(session)
        coord.config_entry = _FakeEntry()
        coord.hass = None  # only used by _fire_event, which won't run on poll 1
        coord._yearly_ranks = {}
        coord._yearly_species_count = 0
        coord._yearly_fetched_date = None
        coord._yearly_items = []
        coord._last_detected = None
        coord._last_notable = None
        coord._seen_species = {}
        coord._sp_codes = {}
        coord._sci_names = {}
        coord._last_seen = {}
        coord._image_urls = {}
        coord._image_attr = {}
        coord._seven_day_data = {}
        coord._prev_recent_species = None
        coord._stores_loaded = True  # skip _load_stores
        for attr in (
            "_store", "_sp_codes_store", "_sci_names_store", "_last_seen_store",
            "_images_store", "_image_attr_store", "_yearly_store",
            "_seven_day_store", "_sticky_store",
        ):
            setattr(coord, attr, _FakeStore())

        data = await coord._async_update_data()

    print("data keys:", list(data.keys()))
    print()

    def head(key):
        v = data.get(key)
        if isinstance(v, list):
            return f"[{len(v)}]" + (f" top={v[0].get('species')!r}" if v else "")
        if isinstance(v, dict):
            return f"{v.get('species')!r}"
        return repr(v)

    for k in ("recent_detections", "last_detection", "daily_count",
              "daily_top_species", "notable_detection", "new_detection",
              "lifetime_species_count", "yearly_top_species", "rarest_species"):
        print(f"  {k:22} -> {head(k)}")

    print("\nnative-overview sensors:")
    for k in ("today_total", "typical_daily_count", "new_species_window",
              "history_earliest", "today_top"):
        print(f"  {k:22} -> {head(k)}")

    ld = data.get("last_detection") or {}
    print("\nlast_detection record:")
    for f in ("species", "scientific_name", "sp_code", "image_url", "audio_url",
              "confidence", "last_seen", "rarity_score",
              "image_credit", "image_credit_url", "image_license", "image_license_url"):
        print(f"  {f:18} {ld.get(f)!r}")

    for key in ("daily_top_species", "yearly_top_species", "rarest_species"):
        lst = data.get(key) or []
        if lst:
            r = lst[0]
            print(f"\n{key}[0] attribution: {r.get('species')!r} -> "
                  f"credit={r.get('image_credit')!r} license={r.get('image_license')!r} "
                  f"credit_url={'yes' if r.get('image_credit_url') else None} "
                  f"license_url={'yes' if r.get('image_license_url') else None}")


if __name__ == "__main__":
    station = sys.argv[1] if len(sys.argv) > 1 else "20184"
    asyncio.run(main(station))
