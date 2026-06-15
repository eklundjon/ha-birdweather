"""Pure response-normalisation + scoring helpers (Haikubox pipeline, BirdWeather
raw keys).

These take plain data and return plain data — no coordinator, HA, or network —
so they live apart from the coordinator's orchestration and are unit-tested
directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .const import CONFIDENCE_BAND_HIGH, CONFIDENCE_BAND_LOW

# Photo credit/license keys threaded from the client onto every record so the
# cards can show attribution (CC BY-SA images require it).
_ATTR_KEYS = ("image_credit", "image_credit_url", "image_license", "image_license_url")


def _parse_dt(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp to an aware datetime (UTC if naive).

    BirdWeather timestamps carry a station-local offset; comparisons stay
    correct because we compare aware datetimes.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _confidence_band(confidence: Any) -> str | None:
    """Qualitative low/medium/high band for a 0–1 confidence (None if unknown).

    Derived from the number, not BirdWeather's near-constant `certainty` string;
    cutoffs live in const (see the note there). Surfaced on records so the cards
    render a label without knowing the thresholds.
    """
    if not isinstance(confidence, (int, float)):
        return None
    if confidence < CONFIDENCE_BAND_LOW:
        return "low"
    if confidence < CONFIDENCE_BAND_HIGH:
        return "medium"
    return "high"


def _filter_by_confidence(
    items: list[dict[str, Any]], min_pct: int
) -> list[dict[str, Any]]:
    """Drop detection events below `min_pct` (0–100) confidence. `min_pct` <= 0
    is a no-op. Events with no numeric confidence are dropped when the filter is
    active (we can't confirm they clear the bar)."""
    if not min_pct or min_pct <= 0:
        return items
    threshold = min_pct / 100.0
    return [
        it
        for it in items
        if isinstance(it, dict)
        and isinstance(it.get("confidence"), (int, float))
        and it["confidence"] >= threshold
    ]


def _filter_by_dt(raw: Any, threshold: datetime) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    items = raw.get("detections", [])
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dt = _parse_dt(item.get("dt"))
        if dt is not None and dt >= threshold:
            out.append(item)
    return out


def _ebird_url(sp_code: str | None) -> str | None:
    return f"https://ebird.org/species/{sp_code}" if sp_code else None


def _allaboutbirds_url(species: str | None) -> str | None:
    # allaboutbirds.org guide URLs key on the common name with spaces → underscores.
    return f"https://www.allaboutbirds.org/guide/{species.replace(' ', '_')}" if species else None


def _peak_hour(hourly: list[int] | None) -> int | None:
    """The hour (0–23) with the most detections in a 24-bucket diel array, or
    None if the array is empty/all-zero."""
    if not hourly or not any(hourly):
        return None
    return max(range(len(hourly)), key=lambda h: hourly[h])


def _ml_url(sp_code: str | None) -> str | None:
    # Macaulay Library catalog keys on the eBird species code (taxonCode) — the
    # same deterministic template BirdWeather's own mlUrl uses, so it's portable
    # to any source that has the sp_code (incl. Haikubox via its eBird map).
    return (
        f"https://search.macaulaylibrary.org/catalog?taxonCode={sp_code}"
        if sp_code
        else None
    )


def _normalise_detections(
    raw: Any, audio_enabled: bool = True
) -> list[dict[str, Any]]:
    """Collapse the flat event list to one record per species, newest first.

    Image URLs come straight from the API (`image`); the latest event's
    `confidence`/`audio` ride along on the per-species record. `audio_url` is
    only surfaced when audio is enabled (else None → no play button).
    """
    if not isinstance(raw, dict):
        return []
    items = raw.get("detections", [])
    if not isinstance(items, list):
        return []

    by_species: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        sp_code = item.get("spCode", "")
        key = sp_code or item.get("cn", "Unknown")
        dt_str = item.get("dt")
        parsed = _parse_dt(dt_str)

        if key not in by_species:
            by_species[key] = {
                "species": item.get("cn", "Unknown"),
                "scientific_name": item.get("sn", ""),
                "sp_code": sp_code,
                "alpha": item.get("alpha"),
                "alpha6": item.get("alpha6"),
                "image_url": item.get("image"),
                "last_seen": dt_str,
                "_last_seen_dt": parsed,
                "audio_url": item.get("audio") if audio_enabled else None,
                "confidence": item.get("confidence"),
                "confidence_band": _confidence_band(item.get("confidence")),
                "count": 0,
                "rarity_score": 0.0,
                "yearly_rank": 0,
                **{k: item.get(k) for k in _ATTR_KEYS},
            }
        rec = by_species[key]
        rec["count"] += 1
        existing = rec["_last_seen_dt"]
        if parsed is not None and (existing is None or parsed > existing):
            rec["last_seen"] = dt_str
            rec["_last_seen_dt"] = parsed
            rec["audio_url"] = item.get("audio") if audio_enabled else None
            rec["confidence"] = item.get("confidence")
            rec["confidence_band"] = _confidence_band(item.get("confidence"))
            if item.get("image"):
                rec["image_url"] = item.get("image")

    results = sorted(
        by_species.values(),
        key=lambda x: x.get("_last_seen_dt") or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    for r in results:
        r.pop("_last_seen_dt", None)
    return results


def _first_seen_per_species(raw: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    best_parsed: dict[str, datetime] = {}
    if not isinstance(raw, dict):
        return out
    items = raw.get("detections", [])
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        sp = item.get("cn", "Unknown")
        dt_str = item.get("dt")
        parsed = _parse_dt(dt_str)
        if parsed is None:
            continue
        existing = best_parsed.get(sp)
        if existing is None or parsed < existing:
            best_parsed[sp] = parsed
            out[sp] = dt_str
    return out


def _process_baseline_count(raw: Any) -> tuple[dict[str, int], int, list[dict[str, Any]]]:
    """Return (species→rank, species_count, items) from a `[{bird, count}]`
    rarity baseline (BirdWeather topSpecies, common-name-keyed)."""
    if not isinstance(raw, list):
        return {}, 0, []
    sorted_items = sorted(
        [item for item in raw if isinstance(item, dict)],
        key=lambda x: int(x.get("count", 0)),
        reverse=True,
    )
    ranks: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for idx, item in enumerate(sorted_items):
        name = item.get("bird", "")
        if not name:
            continue
        rank = idx + 1
        ranks[name] = rank
        items.append({"species": name, "count": int(item.get("count", 0)), "rank": rank})
    return ranks, len(ranks), items


def _apply_rarity_scores(
    detections: list[dict[str, Any]],
    baseline_ranks: dict[str, int],
    baseline_species_count: int,
) -> None:
    denom = max(baseline_species_count, 1)
    for d in detections:
        rank = baseline_ranks.get(d["species"], baseline_species_count)
        d["yearly_rank"] = rank
        d["rarity_score"] = round(rank / denom, 4)


def _apply_notability_scores(
    detections: list[dict[str, Any]],
    now: datetime,
    window_hours: int,
    rarity_weight: float,
) -> None:
    window_seconds = max(window_hours * 3600, 1)
    recency_weight = 1.0 - rarity_weight
    for d in detections:
        rarity = d.get("rarity_score", 0.0) or 0.0
        recency = 0.0
        dt = _parse_dt(d.get("last_seen"))
        if dt is not None:
            age_seconds = max(0.0, (now - dt).total_seconds())
            recency = max(0.0, 1.0 - age_seconds / window_seconds)
        d["notability_score"] = round(rarity_weight * rarity + recency_weight * recency, 4)


def _ranked(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**record, "rank": index + 1} for index, record in enumerate(records)]


def _build_recent_events(
    raw: Any,
    baseline_ranks: dict[str, int],
    baseline_species_count: int,
    image_url_for,
    limit: int,
    audio_enabled: bool = True,
) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    items = raw.get("detections", [])
    if not isinstance(items, list):
        return []
    denom = max(baseline_species_count, 1)
    events: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dt_str = item.get("dt")
        if not isinstance(dt_str, str) or not dt_str:
            continue
        species = item.get("cn", "Unknown")
        sp_code = item.get("spCode", "")
        rank = baseline_ranks.get(species, baseline_species_count)
        events.append({
            "species": species,
            "scientific_name": item.get("sn", ""),
            "sp_code": sp_code,
            "alpha": item.get("alpha"),
            "alpha6": item.get("alpha6"),
            "image_url": item.get("image") or image_url_for(sp_code),
            "last_seen": dt_str,
            "audio_url": item.get("audio") if audio_enabled else None,
            "confidence": item.get("confidence"),
            "confidence_band": _confidence_band(item.get("confidence")),
            "rarity_score": round(rank / denom, 4),
            "yearly_rank": rank,
            **{k: item.get(k) for k in _ATTR_KEYS},
        })
    events.sort(key=lambda e: e.get("last_seen") or "", reverse=True)
    return events[:limit]
