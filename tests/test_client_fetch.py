"""Tests for the BirdWeatherClient data-fetch/parse methods.

Each method issues one GraphQL query and shapes the response; these feed a
canned `{"data": {...}}` payload through a fake session and assert the parse.
"""

from __future__ import annotations

from datetime import date

from custom_components.birdweather.client import BirdWeatherClient


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    async def json(self):
        return self._payload


class _Session:
    def __init__(self, data):
        self._data = data

    def post(self, url, json=None, headers=None):
        return _Resp({"data": self._data})


def _client(data) -> BirdWeatherClient:
    return BirdWeatherClient(_Session(data))


def _species(cn, sci="Sci", code="code"):
    return {
        "commonName": cn, "scientificName": sci, "ebirdCode": code,
        "alpha": "ALPH", "alpha6": "ALPHA6", "imageUrl": "i.jpg",
        "ebirdUrl": "e", "wikipediaUrl": "w", "birdweatherUrl": "bw",
        "imageCredit": '<a href="https://x/u">Pat</a>',
        "imageLicense": "CC BY-SA 4.0", "imageLicenseUrl": "https://cc/x",
    }


# ---- get_detections / get_raw_detections ----------------------------------- #


async def test_get_detections_normalises_nodes() -> None:
    data = {"station": {"detections": {"nodes": [
        {"species": _species("American Robin"), "timestamp": "t",
         "soundscape": {"url": "a.mp3"}, "confidence": 0.9},
    ]}}}
    out = await _client(data).get_detections("1")
    assert out[0]["species"] == "American Robin"
    assert out[0]["audio_url"] == "a.mp3"


async def test_get_raw_detections_emits_pipeline_shape() -> None:
    data = {"station": {"detections": {"nodes": [
        {"species": _species("Barred Owl", code="brdowl"), "timestamp": "2026-06-01T00:00:00Z",
         "soundscape": {"url": "owl.mp3"}, "confidence": 0.7},
    ]}}}
    out = await _client(data).get_raw_detections("1")
    assert "detections" in out
    rec = out["detections"][0]
    # Haikubox raw keys, with the BirdWeather extras threaded alongside.
    assert rec["cn"] == "Barred Owl"
    assert rec["spCode"] == "brdowl"
    assert rec["dt"] == "2026-06-01T00:00:00Z"
    assert rec["audio"] == "owl.mp3"
    assert rec["image_credit"] == "Pat"


async def test_get_raw_detections_empty_station() -> None:
    assert await _client({"station": None}).get_raw_detections("1") == {"detections": []}


# ---- get_baseline_count / get_species_counts ------------------------------- #


async def test_get_baseline_count_keys_by_common_name() -> None:
    data = {"station": {"topSpecies": [
        {"species": {"commonName": "Robin"}, "count": 50},
        {"species": {"commonName": None}, "count": 9},  # skipped (no name)
        {"species": {"commonName": "Owl"}, "count": 3},
    ]}}
    out = await _client(data).get_baseline_count("1", months=2)
    assert out == [{"bird": "Robin", "count": 50}, {"bird": "Owl", "count": 3}]


async def test_get_species_counts_keys_by_scientific_name() -> None:
    data = {"station": {"topSpecies": [
        {"species": {"scientificName": "Turdus migratorius"}, "count": 40},
        {"species": {"scientificName": None}, "count": 5},  # skipped
    ]}}
    out = await _client(data).get_species_counts("1")
    assert out == {"Turdus migratorius": 40}


# ---- get_overview ---------------------------------------------------------- #


async def test_get_overview_derives_scalars_and_today_top() -> None:
    data = {"station": {
        "today": {"detections": 142, "species": 12},
        "baseline": {"detections": 880},  # / baseline_days(10) = 88.0
        "todayTop": [
            {"species": _species("Robin"), "count": 120},
            {"species": {"commonName": None}, "count": 5},  # nameless → skipped
        ],
        "life": {"species": 57},
        "recent": [{"species": {"commonName": "Robin"}}, {"species": {"commonName": "Owl"}}],
        "hist": [{"species": {"commonName": "Robin"}}],  # Owl is new in the window
        "earliestDetectionAt": "2024-01-01T08:30:00-05:00",
    }}
    out = await _client(data).get_overview(
        "1", today=date(2026, 6, 1), new_species_cutoff=date(2026, 5, 2), baseline_days=10
    )
    assert out["today_total"] == 142
    assert out["today_species_count"] == 12
    assert out["lifetime_species"] == 57
    assert out["typical_daily"] == 88.0
    assert out["new_species_window"] == 1  # recent - hist = {Owl}
    assert out["history_earliest"] == "2024-01-01T08:30:00-05:00"
    assert out["today_top"][0]["species"] == "Robin"
    assert out["today_top"][0]["image_credit"] == "Pat"


async def test_get_overview_typical_daily_none_without_baseline() -> None:
    data = {"station": {"today": {}, "baseline": {"detections": 0}}}
    out = await _client(data).get_overview(
        "1", today=date(2026, 6, 1), new_species_cutoff=date(2026, 5, 2), baseline_days=10
    )
    assert out["typical_daily"] is None
    assert out["today_total"] == 0


# ---- get_sensors ----------------------------------------------------------- #


async def test_get_sensors_splits_suites() -> None:
    data = {"station": {"sensors": {
        "environment": {"temperature": 21}, "light": {"clear": 100}, "system": None,
    }}}
    out = await _client(data).get_sensors("1")
    assert out["environment"] == {"temperature": 21}
    assert out["light"] == {"clear": 100}
    assert out["system"] is None


async def test_get_sensors_absent() -> None:
    out = await _client({"station": {"sensors": None}}).get_sensors("1")
    assert out == {"environment": None, "light": None, "system": None}


# ---- get_time_of_day ------------------------------------------------------- #


async def test_get_time_of_day_folds_halfhour_bins_to_hours() -> None:
    data = {"timeOfDayDetectionCounts": [
        {"species": {"commonName": "Robin"}, "bins": [
            {"key": "7.0", "count": 3}, {"key": "7.5", "count": 2},  # both → hour 7
            {"key": "8.0", "count": 1},
            {"key": "bad", "count": 9},  # unparseable → skipped
            {"key": "25", "count": 9},   # out of range → skipped
        ]},
        {"species": {"commonName": None}, "bins": []},  # nameless → skipped
    ]}
    out = await _client(data).get_time_of_day("1", days=7)
    robin = out["by_species"]["Robin"]
    assert robin[7] == 5
    assert robin[8] == 1
    assert out["station"][7] == 5  # station curve is the per-hour sum
    assert sum(out["station"]) == 6


# ---- get_daily_history ----------------------------------------------------- #


async def test_get_daily_history_rows() -> None:
    data = {"dailyDetectionCounts": [
        {"date": "2026-06-01", "total": 50, "counts": [{}, {}, {}]},  # richness 3
        {"date": None, "total": 9, "counts": []},  # no date → skipped
    ]}
    out = await _client(data).get_daily_history("1", date(2026, 6, 1), date(2026, 6, 2))
    assert out == [{"date": "2026-06-01", "total": 50, "species": 3}]


# ---- search / nearby ------------------------------------------------------- #


async def test_search_stations_cleans_nodes() -> None:
    data = {"stations": {"nodes": [
        {"id": "7", "name": "  Yard ", "type": "puc", "coords": {"lat": 1, "lon": 2}},
    ]}}
    out = await _client(data).search_stations(query="yard")
    assert out[0]["name"] == "Yard"
    assert out[0]["type"] == "puc"


async def test_nearby_stations_sorts_by_distance() -> None:
    data = {"stations": {"nodes": [
        {"id": "far", "name": "Far", "coords": {"lat": 46.0, "lon": -93.0}},
        {"id": "near", "name": "Near", "coords": {"lat": 45.01, "lon": -93.0}},
        {"id": "nocoord", "name": "Unknown", "coords": None},
    ]}}
    out = await _client(data).nearby_stations(45.0, -93.0, radius_km=200)
    # Nearest first; the coordless station sorts last with distance None.
    assert [s["id"] for s in out] == ["near", "far", "nocoord"]
    assert out[0]["distance_km"] < out[1]["distance_km"]
    assert out[-1]["distance_km"] is None
