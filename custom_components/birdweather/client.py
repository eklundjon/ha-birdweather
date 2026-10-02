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

# The API returns at most 100 detections per request, whatever `first` asks
# for, so larger samples are fetched as cursor pages of this size.
_DETECTION_PAGE_SIZE = 100

_DETECTIONS_QUERY = """
query stationDetections(
  $id: ID!, $first: Int, $after: String, $classifications: [String!]
) {
  station(id: $id) {
    id
    name
    detections(first: $first, after: $after, classifications: $classifications) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        timestamp
        confidence
        score
        certainty
        behavior
        behaviorCode
        behaviorConfidence
        soundscape { url }
        species {
          classification
          commonName
          scientificName
          ebirdCode
          alpha
          alpha6
          imageUrl
          thumbnailUrl
          imageCredit
          imageLicense
          imageLicenseUrl
          ebirdUrl
          wikipediaUrl
          birdweatherUrl
        }
      }
    }
  }
}
"""

_TOP_SPECIES_QUERY = """
query stationTopSpecies($id: ID!, $ids: [ID!], $period: InputDuration, $limit: Int) {
  station(id: $id) { id }
  topSpecies(stationIds: $ids, classifications: ["avian"], period: $period, limit: $limit) {
    count
    species {
      commonName
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
  $ids: [ID!]
  $today: InputDuration
  $baseline: InputDuration
  $life: InputDuration
  $recent: InputDuration
  $hist: InputDuration
) {
  station(id: $id) { earliestDetectionAt }
  today: counts(stationIds: $ids, classifications: ["avian"], period: $today) { detections species }
  baseline: counts(stationIds: $ids, classifications: ["avian"], period: $baseline) { detections }
  life: counts(stationIds: $ids, classifications: ["avian"], period: $life) { species }
  todayTop: topSpecies(stationIds: $ids, classifications: ["avian"], period: $today, limit: 200) {
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
  recent: topSpecies(stationIds: $ids, classifications: ["avian"], period: $recent, limit: 1000) {
    species { commonName }
  }
  hist: topSpecies(stationIds: $ids, classifications: ["avian"], period: $hist, limit: 2000) {
    species { commonName }
  }
  batToday: counts(stationIds: $ids, classifications: ["bat"], period: $today) { detections }
  batTop: topSpecies(stationIds: $ids, classifications: ["bat"], period: $today, limit: 100) {
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
"""


# Time-of-day ("diel") activity: one BinnedSpeciesCount per species over the
# period, each with sparse half-hourly bins {key (hour as float), count}. Powers
# the per-species hourly sparkline and (summed) the station-wide activity curve.
# Whether a station hears bats: a bat-edition PUC, or any bat detections in a
# recent window (other station types can report bats too).
_HAS_BATS_QUERY = """
query stationHasBats($id: ID!, $ids: [ID!], $period: InputDuration) {
  station(id: $id) { edition }
  counts(stationIds: $ids, classifications: ["bat"], period: $period) { detections }
}
"""

_TIME_OF_DAY_QUERY = """
query stationTimeOfDay($id: ID!, $period: InputDuration) {
  timeOfDayDetectionCounts(stationIds: [$id], period: $period) {
    species { commonName classification }
    bins { key count }
  }
}
"""


# True per-day history (a row per calendar day in the from/to window): `total`
# detections and a per-species `counts` breakdown (one entry per species heard
# that day, so its length is the day's species richness). Powers the long-term
# statistics backfill.
_DAILY_HISTORY_QUERY = """
query stationDailyHistory($id: ID!, $period: InputDuration) {
  dailyDetectionCounts(stationIds: [$id], period: $period) {
    date
    total
    counts { count species { classification } }
  }
}
"""


_STATION_QUERY = """
query station($id: ID!) {
  station(id: $id) {
    id
    name
    type
    edition
    country
    state
    coords { lat lon }
    latestDetectionAt
  }
}
"""


# Onboard PUC hardware sensors. Each sub-suite is null on stations without that
# hardware (e.g. a BirdNET-Pi registered on BirdWeather), so entities are
# created conditionally on what's actually reported. The gas readings come from a
# Bosch BME688 via the BSEC library: `voc` is bVOCeq in ppm (kept), `aqi` is the
# BSEC IAQ index 0–500 (kept), but `eco2` is a BSEC CO2-equivalent *estimate*
# (no real CO2 cell) that's unreliable fleet-wide — ~38% of public PUCs report it
# below the atmospheric floor, some negative — so it's deliberately not requested.
# Spectral light channels (f1–f8, nir), accel/mag, and GPS location are omitted.
_SENSORS_QUERY = """
query stationSensors($id: ID!) {
  station(id: $id) {
    sensors {
      environment {
        temperature
        humidity
        barometricPressure
        soundPressureLevel
        voc
        aqi
        timestamp
      }
      light { clear timestamp }
      system {
        batteryVoltage
        powerSource
        wifiRssi
        sdAvailable
        sdCapacity
        timestamp
      }
    }
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
        nodes = await self._get_detection_nodes(station_id, first)
        return [_normalise_detection(n) for n in nodes]

    async def _get_detection_nodes(
        self, station_id: str, first: int, classifications: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Up to `first` most recent detection nodes, fetched page by page.

        A bounded recent sample, not complete history. Stops early on an empty
        page, a page that adds nothing new, or a missing or repeated cursor, so
        a misbehaving API can't loop; overlapping pages are de-duplicated by
        detection id, so the result can hold fewer than `first` rows.
        `classifications` (BirdWeather's, e.g. ["avian"] or ["bat"]) limits the
        feed to those classes; None fetches every class.
        """
        nodes: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_cursors: set[str] = set()
        after = None
        for _ in range(max(0, math.ceil(first / _DETECTION_PAGE_SIZE))):
            variables: dict[str, Any] = {
                "id": station_id,
                "first": min(_DETECTION_PAGE_SIZE, first - len(nodes)),
                "after": after,
            }
            if classifications is not None:
                variables["classifications"] = classifications
            data = await self._query(_DETECTIONS_QUERY, variables)
            station = data.get("station")
            if station is None:
                raise BirdWeatherError("Station not found or not publicly accessible")
            connection = station.get("detections") or {}
            page = connection.get("nodes") or []
            if not page:
                break
            previous_count = len(nodes)
            for node in page:
                if node.get("id") is not None:
                    detection_id = str(node["id"])
                    if detection_id in seen_ids:
                        continue
                    seen_ids.add(detection_id)
                nodes.append(node)
                if len(nodes) >= first:
                    return nodes
            page_info = connection.get("pageInfo") or {}
            cursor = page_info.get("endCursor")
            if (
                len(nodes) == previous_count
                or not page_info.get("hasNextPage")
                or not isinstance(cursor, str)
                or not cursor
                or cursor in seen_cursors
            ):
                break
            seen_cursors.add(cursor)
            after = cursor
        return nodes

    # --- pipeline-contract adapters --------------------------------------
    #
    # The Haikubox coordinator pipeline (normalise/rarity/notability/recent-
    # events) consumes a raw `{"detections": [{cn, sn, spCode, dt, …}]}` shape
    # and a rarity baseline as `[{bird, count}]`. These two methods present
    # BirdWeather data in exactly that shape so that pipeline reuses verbatim.

    async def get_raw_detections(
        self,
        station_id: str,
        first: int = 300,
        classifications: list[str] | None = None,
    ) -> dict[str, Any]:
        """Recent detection events in the Haikubox raw-payload shape.

        Per-event (not collapsed); carries the BirdWeather extras (`image`,
        `audio`, `confidence`) alongside the haikubox keys so the coordinator
        can thread them through after normalisation, plus `classification`
        ("bird" or "bat") and, for bats, the reported `behavior`.
        `classifications` limits the feed (see _get_detection_nodes).
        """
        nodes = await self._get_detection_nodes(station_id, first, classifications)
        out: list[dict[str, Any]] = []
        for n in nodes:
            sp = n.get("species") or {}
            out.append(
                {
                    "cn": sp.get("commonName"),
                    "sn": sp.get("scientificName"),
                    "spCode": sp.get("ebirdCode") or "",
                    "alpha": sp.get("alpha"),
                    "alpha6": sp.get("alpha6"),
                    "dt": n.get("timestamp"),
                    "image": sp.get("imageUrl"),
                    "audio": (n.get("soundscape") or {}).get("url"),
                    "confidence": n.get("confidence"),
                    "ebird_url": sp.get("ebirdUrl"),
                    "wikipedia_url": sp.get("wikipediaUrl"),
                    "birdweather_url": sp.get("birdweatherUrl"),
                    "classification": _classification(sp),
                    "behavior": n.get("behavior"),
                    "behavior_code": n.get("behaviorCode"),
                    "behavior_confidence": n.get("behaviorConfidence"),
                    **_species_attribution(sp),
                }
            )
        return {"detections": out}

    async def get_baseline_count(
        self, station_id: str, months: int = 1, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Rarity baseline as `[{bird, count}]` (the shape the pipeline ranks),
        keyed by common name. From topSpecies over a trailing `months` window,
        birds only: rarity is a bird measure."""
        data = await self._query(
            _TOP_SPECIES_QUERY,
            {
                "id": station_id,
                "ids": [station_id],
                "period": {"count": months, "unit": "month"},
                "limit": limit,
            },
        )
        if data.get("station") is None:
            raise BirdWeatherError("Station not found or not publicly accessible")
        out: list[dict[str, Any]] = []
        for n in data.get("topSpecies") or []:
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
        / history sensors, in a single GraphQL round-trip. The bird figures are
        filtered to BirdWeather's "avian" class, so bats never count toward
        them; today's bat total and bat species list come back alongside.

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
                "ids": [station_id],
                "today": {"count": 1, "unit": "day"},
                "baseline": {"count": baseline_days, "unit": "day"},
                "life": {"from": _ALLTIME_FROM, "to": today_iso},
                "recent": {"from": cutoff_iso, "to": today_iso},
                "hist": {"from": _ALLTIME_FROM, "to": cutoff_iso},
            },
        )
        st = data.get("station") or {}
        today_c = data.get("today") or {}
        baseline_det = (data.get("baseline") or {}).get("detections") or 0

        def _top(key: str, cls: str) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for n in data.get(key) or []:
                sp = n.get("species") or {}
                name = sp.get("commonName")
                if not name:
                    continue
                out.append(
                    {
                        "species": name,
                        "scientific_name": sp.get("scientificName") or "",
                        "sp_code": sp.get("ebirdCode") or "",
                        "image_url": sp.get("imageUrl"),
                        "count": int(n.get("count") or 0),
                        "classification": cls,
                        **_species_attribution(sp),
                    }
                )
            return out

        def _names(key: str) -> set[str]:
            names: set[str] = set()
            for n in data.get(key) or []:
                cn = (n.get("species") or {}).get("commonName")
                if cn:
                    names.add(cn)
            return names

        return {
            # Full tz-aware ISO timestamp of the station's first-ever detection.
            "history_earliest": st.get("earliestDetectionAt") or None,
            "today_total": int(today_c.get("detections") or 0),
            "today_species_count": int(today_c.get("species") or 0),
            "lifetime_species": int((data.get("life") or {}).get("species") or 0),
            "typical_daily": (
                round(baseline_det / baseline_days, 1) if baseline_det else None
            ),
            "new_species_window": len(_names("recent") - _names("hist")),
            "today_top": _top("todayTop", BIRD),
            "bat_today_total": int((data.get("batToday") or {}).get("detections") or 0),
            "bat_today_top": _top("batTop", BAT),
        }

    async def get_sensors(self, station_id: str) -> dict[str, Any]:
        """Latest onboard hardware-sensor readings, by sub-suite.

        Returns `{"environment": {...}|None, "light": {...}|None,
        "system": {...}|None}` — each sub-suite is None on a station without
        that hardware, which the sensor platform uses to create entities only
        for what's actually reported. SD figures are BigInt (returned as
        strings); the sensor layer coerces them.
        """
        data = await self._query(_SENSORS_QUERY, {"id": station_id})
        sensors = (data.get("station") or {}).get("sensors") or {}
        return {
            "environment": sensors.get("environment"),
            "light": sensors.get("light"),
            "system": sensors.get("system"),
        }

    async def station_has_bats(self, station_id: str, days: int = 30) -> bool:
        """Whether a station hears bats: a bat-edition PUC, or bat detections
        in the trailing `days`. For deciding bat support on an entry set up
        before it existed."""
        data = await self._query(
            _HAS_BATS_QUERY,
            {
                "id": station_id,
                "ids": [station_id],
                "period": {"count": days, "unit": "day"},
            },
        )
        edition = (data.get("station") or {}).get("edition")
        detections = (data.get("counts") or {}).get("detections") or 0
        return edition == "bat" or detections > 0

    async def get_time_of_day(self, station_id: str, days: int = 7) -> dict[str, Any]:
        """Diel activity over the trailing `days`, folded to 24 hourly buckets.

        Returns `{"by_species": {common_name: [24 ints]}, "station": [24 ints]}`.
        The API's bins are sparse half-hourly floats (e.g. 7.0, 7.5); both fold
        into the same integer hour, and `station` is the per-hour sum across all
        species.
        """
        data = await self._query(
            _TIME_OF_DAY_QUERY,
            {"id": station_id, "period": {"count": days, "unit": "day"}},
        )
        rows = data.get("timeOfDayDetectionCounts") or []
        by_species: dict[str, list[int]] = {}
        station = [0] * 24
        for row in rows:
            sp = row.get("species") or {}
            name = sp.get("commonName")
            # Birds only: bats would dominate the station's night-time curve.
            if not name or sp.get("classification", API_BIRDS) != API_BIRDS:
                continue
            hourly = [0] * 24
            for b in row.get("bins") or []:
                try:
                    hour = int(float(b.get("key")))
                except (TypeError, ValueError):
                    continue
                if 0 <= hour <= 23:
                    count = int(b.get("count") or 0)
                    hourly[hour] += count
                    station[hour] += count
            by_species[name] = hourly
        return {"by_species": by_species, "station": station}

    async def get_daily_history(
        self, station_id: str, from_date: date, to_date: date
    ) -> list[dict[str, Any]]:
        """True per-day history over [from_date, to_date], one row per day:
        `{"date": "YYYY-MM-DD", "total": int, "species": int}` where `species`
        is that day's richness (distinct species heard). For the long-term
        statistics backfill."""
        data = await self._query(
            _DAILY_HISTORY_QUERY,
            {
                "id": station_id,
                "period": {"from": from_date.isoformat(), "to": to_date.isoformat()},
            },
        )
        out: list[dict[str, Any]] = []
        for row in data.get("dailyDetectionCounts") or []:
            day = row.get("date")
            if not day:
                continue
            # The day's `total` includes bats, so add up the bird rows instead.
            birds = [
                c for c in row.get("counts") or []
                if ((c.get("species") or {}).get("classification") or API_BIRDS) == API_BIRDS
            ]
            out.append(
                {
                    "date": day,
                    "total": sum(int(c.get("count") or 0) for c in birds),
                    "species": len(birds),
                }
            )
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


# BirdWeather's classification for the feed filters, and ours for records.
API_BIRDS = "avian"
API_BATS = "bat"
BIRD = "bird"
BAT = "bat"


def _classification(sp: dict[str, Any]) -> str:
    """BAT for a species BirdWeather classifies as a bat, else BIRD."""
    return BAT if sp.get("classification") == API_BATS else BIRD


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
        # "bat" for a bat-edition PUC (pre-ticks bat support in the setup flow).
        "edition": node.get("edition"),
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
