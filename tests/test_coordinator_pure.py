"""Tests for the pure, module-level helpers in coordinator.py.

These take plain data and return plain data — no HA, no network, no coordinator
instance — so they're the cheapest place to lock down the scoring/normalisation
contract the sensors and cards depend on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.birdweather.normalize import (
    _allaboutbirds_url,
    _apply_notability_scores,
    _apply_rarity_scores,
    _build_recent_events,
    _confidence_band,
    _ebird_url,
    _filter_by_confidence,
    _filter_by_dt,
    _first_seen_per_species,
    _ml_url,
    _normalise_detections,
    _parse_dt,
    _peak_hour,
    _process_baseline_count,
    _ranked,
)

_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _iso(minutes_ago: int) -> str:
    return (_NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S+00:00")


# ---- _parse_dt ------------------------------------------------------------- #


def test_parse_dt_naive_assumed_utc() -> None:
    dt = _parse_dt("2026-06-01T12:00:00")
    assert dt == datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def test_parse_dt_keeps_offset() -> None:
    dt = _parse_dt("2026-06-01T12:00:00-05:00")
    assert dt is not None
    assert dt.utcoffset() == timedelta(hours=-5)


def test_parse_dt_bad_values_return_none() -> None:
    assert _parse_dt("not-a-date") is None
    assert _parse_dt("") is None
    assert _parse_dt(None) is None
    assert _parse_dt(12345) is None


# ---- _confidence_band ------------------------------------------------------ #


def test_confidence_band_thresholds() -> None:
    assert _confidence_band(0.0) == "low"
    assert _confidence_band(0.54) == "low"
    assert _confidence_band(0.55) == "medium"
    assert _confidence_band(0.79) == "medium"
    assert _confidence_band(0.80) == "high"
    assert _confidence_band(1.0) == "high"


def test_confidence_band_non_numeric_is_none() -> None:
    assert _confidence_band(None) is None
    assert _confidence_band("high") is None


# ---- _filter_by_confidence ------------------------------------------------- #


def test_filter_by_confidence_noop_at_zero() -> None:
    items = [{"confidence": 0.1}, {"confidence": 0.9}, {"no": "conf"}]
    assert _filter_by_confidence(items, 0) is items


def test_filter_by_confidence_drops_below_and_unscored() -> None:
    items = [{"confidence": 0.4}, {"confidence": 0.8}, {"x": 1}]
    out = _filter_by_confidence(items, 50)
    assert out == [{"confidence": 0.8}]


# ---- _filter_by_dt --------------------------------------------------------- #


def test_filter_by_dt_keeps_at_or_after_threshold() -> None:
    raw = {"detections": [{"dt": _iso(10)}, {"dt": _iso(120)}, {"dt": "bad"}]}
    out = _filter_by_dt(raw, _NOW - timedelta(hours=1))
    assert out == [{"dt": _iso(10)}]


def test_filter_by_dt_bad_shapes() -> None:
    assert _filter_by_dt(None, _NOW) == []
    assert _filter_by_dt({"detections": "nope"}, _NOW) == []
    assert _filter_by_dt({}, _NOW) == []


# ---- url builders ---------------------------------------------------------- #


def test_url_builders() -> None:
    assert _ebird_url("amerob") == "https://ebird.org/species/amerob"
    assert _ebird_url(None) is None
    assert _allaboutbirds_url("American Robin") == (
        "https://www.allaboutbirds.org/guide/American_Robin"
    )
    assert _allaboutbirds_url(None) is None
    assert _ml_url("amerob") == (
        "https://search.macaulaylibrary.org/catalog?taxonCode=amerob"
    )
    assert _ml_url(None) is None


# ---- _peak_hour ------------------------------------------------------------ #


def test_peak_hour_picks_busiest_bucket() -> None:
    hourly = [0] * 24
    hourly[8] = 50
    hourly[17] = 30
    assert _peak_hour(hourly) == 8


def test_peak_hour_empty_or_allzero_is_none() -> None:
    assert _peak_hour(None) is None
    assert _peak_hour([]) is None
    assert _peak_hour([0] * 24) is None


# ---- _normalise_detections ------------------------------------------------- #


def test_normalise_collapses_per_species_newest_first() -> None:
    raw = {"detections": [
        {"cn": "American Robin", "sn": "Turdus migratorius", "spCode": "amerob",
         "dt": _iso(40), "image": "a.jpg", "audio": "a.mp3", "confidence": 0.9},
        {"cn": "American Robin", "sn": "Turdus migratorius", "spCode": "amerob",
         "dt": _iso(10), "image": "b.jpg", "audio": "b.mp3", "confidence": 0.95},
        {"cn": "Barred Owl", "sn": "Strix varia", "spCode": "brdowl",
         "dt": _iso(20), "image": "o.jpg", "confidence": 0.6},
    ]}
    out = _normalise_detections(raw)
    assert [r["species"] for r in out] == ["American Robin", "Barred Owl"]
    robin = out[0]
    assert robin["count"] == 2
    # The newest event wins for last_seen / image / audio / confidence.
    assert robin["last_seen"] == _iso(10)
    assert robin["image_url"] == "b.jpg"
    assert robin["audio_url"] == "b.mp3"
    assert robin["confidence"] == 0.95
    assert robin["confidence_band"] == "high"
    # The _last_seen_dt scratch key is stripped from the output.
    assert "_last_seen_dt" not in robin


def test_normalise_audio_suppressed_when_disabled() -> None:
    raw = {"detections": [{"cn": "Robin", "spCode": "amerob", "dt": _iso(5), "audio": "a.mp3"}]}
    out = _normalise_detections(raw, audio_enabled=False)
    assert out[0]["audio_url"] is None


def test_normalise_bad_shapes() -> None:
    assert _normalise_detections(None) == []
    assert _normalise_detections({"detections": "x"}) == []


# ---- _first_seen_per_species ----------------------------------------------- #


def test_first_seen_keeps_earliest() -> None:
    raw = {"detections": [
        {"cn": "Robin", "dt": _iso(10)},
        {"cn": "Robin", "dt": _iso(100)},
        {"cn": "Owl", "dt": _iso(50)},
        {"cn": "Skip", "dt": "bad"},
    ]}
    out = _first_seen_per_species(raw)
    assert out["Robin"] == _iso(100)
    assert out["Owl"] == _iso(50)
    assert "Skip" not in out


# ---- _process_baseline_count ----------------------------------------------- #


def test_process_baseline_count_ranks_by_count_desc() -> None:
    raw = [{"bird": "Robin", "count": 5}, {"bird": "Owl", "count": 20}, {"bird": "", "count": 1}]
    ranks, count, items = _process_baseline_count(raw)
    # Sorted by count desc: Owl(20), Robin(5), <blank>(1). The blank name is
    # skipped from the rank map but still occupies its sort slot.
    assert ranks == {"Owl": 1, "Robin": 2}
    assert count == 2
    assert items[0] == {"species": "Owl", "count": 20, "rank": 1}


def test_process_baseline_count_bad_shape() -> None:
    assert _process_baseline_count(None) == ({}, 0, [])


# ---- _apply_rarity_scores -------------------------------------------------- #


def test_apply_rarity_scores_uses_rank_over_count() -> None:
    dets = [{"species": "Owl"}, {"species": "Unknown Bird"}]
    _apply_rarity_scores(dets, {"Owl": 1, "Robin": 2}, 2)
    assert dets[0]["yearly_rank"] == 1
    assert dets[0]["rarity_score"] == 0.5
    # Absent species fall to the bottom rank (== species count) → score 1.0.
    assert dets[1]["yearly_rank"] == 2
    assert dets[1]["rarity_score"] == 1.0


# ---- _apply_notability_scores ---------------------------------------------- #


def test_apply_notability_blends_rarity_and_recency() -> None:
    dets = [{"rarity_score": 1.0, "last_seen": _iso(0)}]
    _apply_notability_scores(dets, _NOW, window_hours=24, rarity_weight=0.7)
    # rarity 1.0 weighted .7, recency ~1.0 (age 0) weighted .3 → ~1.0
    assert dets[0]["notability_score"] == 1.0


def test_apply_notability_recency_decays_over_window() -> None:
    dets = [{"rarity_score": 0.0, "last_seen": _iso(12 * 60)}]  # half a 24h window old
    _apply_notability_scores(dets, _NOW, window_hours=24, rarity_weight=0.0)
    assert dets[0]["notability_score"] == 0.5


# ---- _ranked --------------------------------------------------------------- #


def test_ranked_adds_one_based_rank() -> None:
    out = _ranked([{"species": "a"}, {"species": "b"}])
    assert [r["rank"] for r in out] == [1, 2]


# ---- _build_recent_events -------------------------------------------------- #


def test_build_recent_events_sorts_and_caps() -> None:
    raw = {"detections": [
        {"cn": "Robin", "spCode": "amerob", "dt": _iso(30), "confidence": 0.9},
        {"cn": "Owl", "spCode": "brdowl", "dt": _iso(5), "confidence": 0.5},
        {"cn": "Jay", "spCode": "blujay", "dt": _iso(60)},
    ]}
    events = _build_recent_events(
        raw, {"Owl": 1}, 1, image_url_for=lambda c: f"/img/{c}.jpg", limit=2
    )
    assert [e["species"] for e in events] == ["Owl", "Robin"]  # newest first, capped at 2
    owl = events[0]
    assert owl["yearly_rank"] == 1
    assert owl["confidence_band"] == "low"
    # image falls back to image_url_for when the event has no inline image.
    assert owl["image_url"] == "/img/brdowl.jpg"


def test_build_recent_events_skips_dateless_and_bad_shapes() -> None:
    assert _build_recent_events(None, {}, 0, lambda c: None, 50) == []
    raw = {"detections": [{"cn": "NoDate"}, {"cn": "Ok", "spCode": "x", "dt": _iso(1)}]}
    events = _build_recent_events(raw, {}, 0, lambda c: None, 50)
    assert [e["species"] for e in events] == ["Ok"]
