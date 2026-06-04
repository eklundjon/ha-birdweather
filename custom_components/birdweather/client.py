"""Thin async client for the BirdWeather public GraphQL API.

BirdWeather exposes a single GraphQL endpoint that serves *public* station
data anonymously — no token needed (the token/REST surface is only for
writing or private stations, neither of which a read-only HA integration
needs). This module covers the three things the integration consumes:

  * station discovery (bounding-box + free-text search) for onboarding,
  * recent detections for a station, and
  * per-species counts for the rarity baseline.

It is deliberately HA-agnostic and dependency-light (just aiohttp) so it can
be exercised against the live API outside Home Assistant — see
`scripts/smoke.py`. Field shapes were pinned against the live schema:
`Station.coords{lat,lon}`, `Detection{timestamp,confidence,score,certainty,
species{...},soundscape{url}}`, `Species{commonName,scientificName,ebirdCode,
imageUrl,thumbnailUrl,ebirdUrl,wikipediaUrl,...}`.
"""

from __future__ import annotations

import html
import math
import re
from datetime import date
from typing import Any

import aiohttp

API_URL = "https://app.birdweather.com/graphql"

# BirdWeather launched ~2021; this lower bound is "before any station existed"
# and serves as the from-edge of all-time windows (the API's from/to InputDuration
# requires both ends, so there's no open-ended "since the beginning").
_ALLTIME_FROM = "2015-01-01"

# --- GraphQL documents -------------------------------------------------------

_STATIONS_QUERY = """
query stations($query: String, $first: Int, $ne: InputLocation, $sw: InputLocation) {
  stations(query: $query, first: $first, ne: $ne, sw: $sw) {
    totalCount
    nodes {
      id
      name
      type
      country
      state
      coords { lat lon }
      latestDetectionAt
    }
  }
}
"""

_DETECTIONS_QUERY = """
query stationDetections($id: ID!, $first: Int) {
  station(id: $id) {
    id
    name
    detections(first: $first) {
      nodes {
        id
        timestamp
        confidence
        score
        certainty
        soundscape { url }
        species {
          commonName
          scientificName
          ebirdCode
          imageUrl
          thumbnailUrl
          imageCredit
          imageLicense
          imageLicenseUrl
          ebirdUrl
          wikipediaUrl
        }
      }
    }
  }
}
"""

_TOP_SPECIES_QUERY = """
query stationTopSpecies($id: ID!, $period: InputDuration, $limit: Int) {
  station(id: $id) {
    topSpecies(period: $period, limit: $limit) {
      count
      species {
        commonName
        scientificName
        ebirdCode
        imageUrl
        imageCredit
        imageLicense
        imageLicenseUrl
      }
    }
  }
}
"""


# One round-trip powering the activity / diversity / new-species / history
# sensors entirely from BirdWeather's native per-period aggregates. `today` is a
# trailing 1-day window (true counts, not a sample); `baseline` a trailing 30-day
# total for the "typical day"; `life` an all-time distinct-species count; and the
# `recent` vs `hist` topSpecies sets diff to find species first heard recently.
_OVERVIEW_QUERY = """
query stationOverview(
  $id: ID!
  $today: InputDuration
  $baseline: InputDuration
  $life: InputDuration
  $recent: InputDuration
  $hist: InputDuration
) {
  station(id: $id) {
    earliestDetectionAt
    today: counts(period: $today) { detections species }
    baseline: counts(period: $baseline) { detections }
    life: counts(period: $life) { species }
    todayTop: topSpecies(period: $today, limit: 200) {
      count
      species {
        commonName
        scientificName
        ebirdCode
        imageUrl
        imageCredit
        imageLicense
        imageLicenseUrl
      }
    }
    recent: topSpecies(period: $recent, limit: 1000) { species { commonName } }
    hist: topSpecies(period: $hist, limit: 2000) { species { commonName } }
  }
}
"""


_STATION_QUERY = """
query station($id: ID!) {
  station(id: $id) {
    id
    name
    type
    country
    state
    coords { lat lon }
    latestDetectionAt
  }
}
"""


class BirdWeatherError(Exception):
    """Raised when the API returns transport or GraphQL-level errors."""


class BirdWeatherClient:
    """Minimal async wrapper over the BirdWeather GraphQL API."""

    def __init__(self, session: aiohttp.ClientSession, url: str = API_URL) -> None:
        self._session = session
        self._url = url

    async def _query(self, document: str, variables: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._session.post(
                self._url,
                json={"query": document, "variables": variables},
                headers={"User-Agent": "ha-birdweather"},
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json()
        except aiohttp.ClientError as err:
            raise BirdWeatherError(f"transport error: {err}") from err
        if payload.get("errors"):
            raise BirdWeatherError(str(payload["errors"]))
        return payload["data"]

    # --- discovery -----------------------------------------------------------

    async def search_stations(
        self,
        *,
        query: str | None = None,
        ne: dict[str, float] | None = None,
        sw: dict[str, float] | None = None,
        first: int = 25,
    ) -> list[dict[str, Any]]:
        """Return public stations matching a free-text query and/or bounding box."""
        data = await self._query(
            _STATIONS_QUERY,
            {"query": query, "first": first, "ne": ne, "sw": sw},
        )
        return [_clean_station(n) for n in data["stations"]["nodes"]]

    async def get_station(self, station_id: str) -> dict[str, Any] | None:
        """Look up a single public station by ID (validation + canonical name)."""
        data = await self._query(_STATION_QUERY, {"id": station_id})
        node = data.get("station")
        return _clean_station(node) if node else None

    async def nearby_stations(
        self, lat: float, lon: float, radius_km: float = 25.0, first: int = 25
    ) -> list[dict[str, Any]]:
        """Public stations within ~radius_km of a point, nearest first.

        Builds a bounding box from the radius (1 deg lat ~= 111 km; lon scaled
        by cos(lat)), queries it, then sorts the results by great-circle
        distance and annotates each with `distance_km`.
        """
        dlat = radius_km / 111.0
        dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 1e-6))
        ne = {"lat": lat + dlat, "lon": lon + dlon}
        sw = {"lat": lat - dlat, "lon": lon - dlon}
        stations = await self.search_stations(ne=ne, sw=sw, first=first)
        for s in stations:
            c = s.get("coords") or {}
            s["distance_km"] = (
                _haversine_km(lat, lon, c["lat"], c["lon"])
                if c.get("lat") is not None
                else None
            )
        stations.sort(key=lambda s: (s["distance_km"] is None, s["distance_km"] or 0))
        return stations

    # --- data ----------------------------------------------------------------

    async def get_detections(self, station_id: str, first: int = 50) -> list[dict[str, Any]]:
        """Most recent detections for a station, normalised to the common shape."""
        data = await self._query(_DETECTIONS_QUERY, {"id": station_id, "first": first})
        station = data.get("station") or {}
        nodes = (station.get("detections") or {}).get("nodes") or []
        return [_normalise_detection(n) for n in nodes]

    # --- pipeline-contract adapters --------------------------------------
    #
    # The Haikubox coordinator pipeline (normalise/rarity/notability/recent-
    # events) consumes a raw `{"detections": [{cn, sn, spCode, dt, …}]}` shape
    # and a rarity baseline as `[{bird, count}]`. These two methods present
    # BirdWeather data in exactly that shape so that pipeline reuses verbatim.

    async def get_raw_detections(
        self, station_id: str, first: int = 300
    ) -> dict[str, Any]:
        """Recent detection events in the Haikubox raw-payload shape.

        Per-event (not collapsed); carries the BirdWeather extras (`image`,
        `audio`, `confidence`) alongside the haikubox keys so the coordinator
        can thread them through after normalisation.
        """
        data = await self._query(_DETECTIONS_QUERY, {"id": station_id, "first": first})
        station = data.get("station") or {}
        nodes = (station.get("detections") or {}).get("nodes") or []
        out: list[dict[str, Any]] = []
        for n in nodes:
            sp = n.get("species") or {}
            out.append(
                {
                    "cn": sp.get("commonName"),
                    "sn": sp.get("scientificName"),
                    "spCode": sp.get("ebirdCode") or "",
                    "dt": n.get("timestamp"),
                    "image": sp.get("imageUrl"),
                    "audio": (n.get("soundscape") or {}).get("url"),
                    "confidence": n.get("confidence"),
                    **_species_attribution(sp),
                }
            )
        return {"detections": out}

    async def get_baseline_count(
        self, station_id: str, months: int = 1, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Rarity baseline as `[{bird, count}]` (the shape the pipeline ranks),
        keyed by common name. From topSpecies over a trailing `months` window."""
        data = await self._query(
            _TOP_SPECIES_QUERY,
            {"id": station_id, "period": {"count": months, "unit": "month"}, "limit": limit},
        )
        station = data.get("station") or {}
        nodes = station.get("topSpecies") or []
        out: list[dict[str, Any]] = []
        for n in nodes:
            cn = (n.get("species") or {}).get("commonName")
            if cn:
                out.append({"bird": cn, "count": n.get("count") or 0})
        return out

    async def get_overview(
        self,
        station_id: str,
        *,
        today: date,
        new_species_cutoff: date,
        baseline_days: int,
    ) -> dict[str, Any]:
        """Native per-period aggregates for the activity / diversity / new-species
        / history sensors, in a single GraphQL round-trip.

        `new_species_cutoff` is `today - NEW_SPECIES_WINDOW_DAYS`; `baseline_days`
        sizes the typical-day divisor. Returns derived scalars plus a normalised
        today-top list (already ranked by count, with image + scientific name
        straight from the API). BirdWeather predates `_ALLTIME_FROM`, which stands
        in for "all time" on the from/to windows (InputDuration needs both bounds).
        """
        today_iso = today.isoformat()
        cutoff_iso = new_species_cutoff.isoformat()
        data = await self._query(
            _OVERVIEW_QUERY,
            {
                "id": station_id,
                "today": {"count": 1, "unit": "day"},
                "baseline": {"count": baseline_days, "unit": "day"},
                "life": {"from": _ALLTIME_FROM, "to": today_iso},
                "recent": {"from": cutoff_iso, "to": today_iso},
                "hist": {"from": _ALLTIME_FROM, "to": cutoff_iso},
            },
        )
        st = data.get("station") or {}
        today_c = st.get("today") or {}
        baseline_det = (st.get("baseline") or {}).get("detections") or 0

        today_top: list[dict[str, Any]] = []
        for n in st.get("todayTop") or []:
            sp = n.get("species") or {}
            name = sp.get("commonName")
            if not name:
                continue
            today_top.append(
                {
                    "species": name,
                    "scientific_name": sp.get("scientificName") or "",
                    "sp_code": sp.get("ebirdCode") or "",
                    "image_url": sp.get("imageUrl"),
                    "count": int(n.get("count") or 0),
                    **_species_attribution(sp),
                }
            )

        def _names(key: str) -> set[str]:
            names: set[str] = set()
            for n in st.get(key) or []:
                cn = (n.get("species") or {}).get("commonName")
                if cn:
                    names.add(cn)
            return names

        return {
            # Full tz-aware ISO timestamp of the station's first-ever detection.
            "history_earliest": st.get("earliestDetectionAt") or None,
            "today_total": int(today_c.get("detections") or 0),
            "today_species_count": int(today_c.get("species") or 0),
            "lifetime_species": int((st.get("life") or {}).get("species") or 0),
            "typical_daily": (
                round(baseline_det / baseline_days, 1) if baseline_det else None
            ),
            "new_species_window": len(_names("recent") - _names("hist")),
            "today_top": today_top,
        }

    async def get_species_counts(
        self, station_id: str, months: int = 1, limit: int = 200
    ) -> dict[str, int]:
        """Map of scientific_name -> detection count over the trailing N months,
        ranked highest-first by the API. Serves as the rarity baseline (the
        BirdWeather analogue of Haikubox's yearly_ranks)."""
        data = await self._query(
            _TOP_SPECIES_QUERY,
            {"id": station_id, "period": {"count": months, "unit": "month"}, "limit": limit},
        )
        station = data.get("station") or {}
        nodes = station.get("topSpecies") or []
        out: dict[str, int] = {}
        for n in nodes:
            sp = n.get("species") or {}
            sci = sp.get("scientificName")
            if sci:
                out[sci] = n.get("count") or 0
        return out


# --- normalisation -----------------------------------------------------------

_HREF_RE = re.compile(r'href="([^"]+)"', re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _parse_image_credit(raw: str | None) -> tuple[str | None, str | None]:
    """BirdWeather's `imageCredit` is HTML (usually a single `<a href>` to a
    Wikimedia/contributor page). Return `(plain-text credit, href)` — never the
    raw HTML, so it's safe to put in a state attribute / render as plain text.
    """
    if not raw:
        return None, None
    m = _HREF_RE.search(raw)
    url = html.unescape(m.group(1)) if m else None
    if url and url.startswith("//"):  # protocol-relative → https
        url = "https:" + url
    text = html.unescape(_TAG_RE.sub("", raw)).strip()
    return (text or None), (url or None)


def _species_attribution(sp: dict[str, Any]) -> dict[str, Any]:
    """Photo credit/license for a Species node, as clean (non-HTML) fields."""
    credit, credit_url = _parse_image_credit(sp.get("imageCredit"))
    return {
        "image_credit": credit,
        "image_credit_url": credit_url,
        "image_license": sp.get("imageLicense") or None,
        "image_license_url": sp.get("imageLicenseUrl") or None,
    }


def _clean_station(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node["id"],
        "name": (node.get("name") or "").strip() or f"Station {node['id']}",
        "type": node.get("type"),
        "country": node.get("country"),
        "state": node.get("state"),
        "coords": node.get("coords"),
        "latest_detection_at": node.get("latestDetectionAt"),
    }


def _normalise_detection(node: dict[str, Any]) -> dict[str, Any]:
    """Map a BirdWeather Detection onto the haikubox `detections[]` contract,
    carrying the extra BirdWeather-only fields (confidence/audio/links)."""
    sp = node.get("species") or {}
    return {
        "species": sp.get("commonName"),
        "scientific_name": sp.get("scientificName"),
        "sp_code": sp.get("ebirdCode"),
        "image_url": sp.get("imageUrl"),
        "thumbnail_url": sp.get("thumbnailUrl"),
        "last_seen": node.get("timestamp"),
        # BirdWeather extras (no Haikubox equivalent):
        "confidence": node.get("confidence"),
        "score": node.get("score"),
        "certainty": node.get("certainty"),
        "audio_url": (node.get("soundscape") or {}).get("url"),
        "ebird_url": sp.get("ebirdUrl"),
        "wikipedia_url": sp.get("wikipediaUrl"),
        **_species_attribution(sp),
    }


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))
