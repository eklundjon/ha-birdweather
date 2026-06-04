from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import BirdWeatherClient, BirdWeatherError
from .const import (
    CONF_ABSENCE_DAYS,
    CONF_NOTABLE_RARITY_WEIGHT,
    ACTIVITY_BASELINE_DAYS,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    DAILY_WINDOW_HOURS,
    DEFAULT_ABSENCE_DAYS,
    DEFAULT_NOTABLE_RARITY_WEIGHT,
    DEFAULT_SCAN_INTERVAL,
    DETECTION_FETCH_LIMIT,
    DOMAIN,
    EVENT_BIRDWEATHER,
    LAST_DETECTION_EVENT_LIMIT,
    NEW_SPECIES_HISTORY_LIMIT,
    NEW_SPECIES_WINDOW_DAYS,
    NOTABILITY_WINDOW_HOURS,
    RARITY_PERIOD_MONTHS,
    RECENT_WINDOW_HOURS,
    CONF_WATCHED_EXTRA,
    CONF_WATCHED_SPECIES,
    TRIGGER_NEW_SPECIES,
    TRIGGER_UNUSUAL_VISITOR,
    TRIGGER_WATCHED_SPECIES,
)

_LOGGER = logging.getLogger(__name__)

_STORE_VERSION = 1

type BirdWeatherConfigEntry = ConfigEntry[BirdWeatherCoordinator]


class BirdWeatherCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the BirdWeather GraphQL API and normalises it for sensors.

    The data pipeline (normalise / rarity / notability / recency / new-species
    / unusual-visitor / sticky stores / 7-day / events) is the Haikubox
    pipeline reused verbatim; only the data *source* differs. The client
    presents BirdWeather data in the raw shape the pipeline expects, and
    BirdWeather supplies image URLs directly (no image cache needed).
    """

    def __init__(self, hass: HomeAssistant, entry: BirdWeatherConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.station_id = station_id = entry.data[CONF_STATION_ID]
        self.device_name = entry.data.get(CONF_STATION_NAME, "BirdWeather Station")
        self._session = async_get_clientsession(hass)
        self._client = BirdWeatherClient(self._session)

        # Rarity baseline (topSpecies counts) — refreshed once per calendar day.
        self._baseline_ranks: dict[str, int] = {}
        self._baseline_species_count: int = 0
        self._baseline_fetched_date: date | None = None

        # Sticky records — set on first detection, never cleared; persisted.
        self._last_detected: dict[str, Any] | None = None
        self._last_notable: dict[str, Any] | None = None

        # Persistent stores
        self._store           = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.seen_species")
        self._sp_codes_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.sp_codes")
        self._sci_names_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.sci_names")
        self._last_seen_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.last_seen")
        self._images_store     = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.image_urls")
        self._image_attr_store = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.image_attr")
        self._yearly_store     = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.yearly")
        self._seven_day_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.seven_day")
        self._sticky_store     = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.sticky")

        # In-memory store state
        self._seen_species: dict[str, str] = {}       # species → first_seen ISO
        self._sp_codes: dict[str, str] = {}           # species → sp_code
        self._sci_names: dict[str, str] = {}          # species → scientific_name
        self._last_seen: dict[str, str] = {}          # species → last_seen ISO
        self._image_urls: dict[str, str] = {}         # sp_code → image URL
        # sp_code → {image_credit, image_credit_url, image_license, image_license_url}
        self._image_attr: dict[str, dict[str, Any]] = {}
        self._baseline_items: list[dict[str, Any]] = []
        self._seven_day_data: dict[str, list] = {}
        self._stores_loaded: bool = False

        # unusual_visitor edge detection (None until first poll baselines).
        self._prev_recent_species: set[str] | None = None

    # ------------------------------------------------------------------
    # DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        if not self._stores_loaded:
            await self._load_stores()

        # UTC-anchored day boundaries (matches the pipeline's assumptions).
        today = datetime.now(timezone.utc).date()

        # Refresh the rarity baseline once per calendar day.
        if self._baseline_fetched_date != today:
            try:
                baseline_raw = await self._client.get_baseline_count(
                    self.station_id, months=RARITY_PERIOD_MONTHS
                )
                self._baseline_ranks, self._baseline_species_count, self._baseline_items = (
                    _process_baseline_count(baseline_raw)
                )
                self._baseline_fetched_date = today
                await self._yearly_store.async_save(self._baseline_items)
            except (aiohttp.ClientError, BirdWeatherError) as err:
                _LOGGER.warning("Could not fetch rarity baseline: %s", err)

        if not self._baseline_ranks:
            raise UpdateFailed(
                "Rarity baseline not yet available — topSpecies fetch failed on "
                "first poll and there is no cached baseline"
            )

        try:
            raw_all = await self._client.get_raw_detections(
                self.station_id, first=DETECTION_FETCH_LIMIT
            )
        except (aiohttp.ClientError, BirdWeatherError) as err:
            raise UpdateFailed(f"Error communicating with BirdWeather API: {err}") from err

        now = datetime.now(timezone.utc)
        # The fetch returns the most-recent N events regardless of age; carve
        # the trailing 24h (and the 1h subset) out of it client-side. Busy
        # stations may exhaust the limit inside 24h — see DETECTION_FETCH_LIMIT.
        daily_raw = {"detections": _filter_by_dt(raw_all, now - timedelta(hours=DAILY_WINDOW_HOURS))}
        recent_raw = {"detections": _filter_by_dt(daily_raw, now - timedelta(hours=RECENT_WINDOW_HOURS))}

        detections = _normalise_detections(recent_raw)
        _apply_rarity_scores(detections, self._baseline_ranks, self._baseline_species_count)

        daily_count = sorted(
            _normalise_detections(daily_raw),
            key=lambda x: x.get("count", 0),
            reverse=True,
        )
        _apply_rarity_scores(daily_count, self._baseline_ranks, self._baseline_species_count)

        # Snapshot last_seen before the update loop (for absence-gap measuring).
        prior_last_seen = dict(self._last_seen)

        # Update sp_codes / scientific_name / last_seen / image lookups.
        sp_codes_dirty = sci_names_dirty = last_seen_dirty = images_dirty = False
        image_attr_dirty = False
        for d in detections:
            sp = d["species"]
            if d.get("sp_code") and sp not in self._sp_codes:
                self._sp_codes[sp] = d["sp_code"]
                sp_codes_dirty = True
            if d.get("scientific_name") and sp not in self._sci_names:
                self._sci_names[sp] = d["scientific_name"]
                sci_names_dirty = True
            if d.get("sp_code") and d.get("image_url"):
                if self._image_urls.get(d["sp_code"]) != d["image_url"]:
                    self._image_urls[d["sp_code"]] = d["image_url"]
                    images_dirty = True
            if self._cache_image_attr(d.get("sp_code", ""), d):
                image_attr_dirty = True
            ts = d.get("last_seen")
            if ts and ts > self._last_seen.get(sp, ""):
                self._last_seen[sp] = ts
                last_seen_dirty = True

        seen_dirty = False

        # Fresh-install bootstrap for _seen_species from the 24h window.
        if not self._seen_species and daily_count:
            first_seen_by_species = _first_seen_per_species(daily_raw)
            for d in daily_count:
                sp = d["species"]
                if not sp:
                    continue
                if d.get("sp_code"):
                    if sp not in self._sp_codes:
                        self._sp_codes[sp] = d["sp_code"]
                        sp_codes_dirty = True
                    if d.get("image_url") and self._image_urls.get(d["sp_code"]) != d["image_url"]:
                        self._image_urls[d["sp_code"]] = d["image_url"]
                        images_dirty = True
                if self._cache_image_attr(d.get("sp_code", ""), d):
                    image_attr_dirty = True
                if d.get("scientific_name") and sp not in self._sci_names:
                    self._sci_names[sp] = d["scientific_name"]
                    sci_names_dirty = True
                ts = d.get("last_seen")
                if ts and ts > self._last_seen.get(sp, ""):
                    self._last_seen[sp] = ts
                    last_seen_dirty = True
                self._seen_species[sp] = (
                    first_seen_by_species.get(sp) or d.get("last_seen") or today.isoformat()
                )
                seen_dirty = True

        if sp_codes_dirty:
            await self._sp_codes_store.async_save(self._sp_codes)
        if sci_names_dirty:
            await self._sci_names_store.async_save(self._sci_names)
        if last_seen_dirty:
            await self._last_seen_store.async_save(self._last_seen)
        if images_dirty:
            await self._images_store.async_save(self._image_urls)
        if image_attr_dirty:
            await self._image_attr_store.async_save(self._image_attr)

        # Live new-species detection from the recent window.
        newly_seen: set[str] = set()
        for d in detections:
            sp = d["species"]
            if sp not in self._seen_species:
                self._seen_species[sp] = d.get("last_seen") or today.isoformat()
                newly_seen.add(sp)
                seen_dirty = True
        if seen_dirty:
            await self._store.async_save(self._seen_species)

        seven_day_rare = await self._update_seven_day(daily_count, today)

        sticky_dirty = False
        if detections:
            if not self._last_detected or detections[0].get("species") != self._last_detected.get("species"):
                sticky_dirty = True
            self._last_detected = detections[0]

        rarity_weight = self.config_entry.options.get(
            CONF_NOTABLE_RARITY_WEIGHT, DEFAULT_NOTABLE_RARITY_WEIGHT
        ) / 100.0
        _apply_notability_scores(daily_count, now, NOTABILITY_WINDOW_HOURS, rarity_weight)
        notable = sorted(daily_count, key=lambda x: x.get("notability_score", 0), reverse=True)
        if notable:
            if not self._last_notable or notable[0].get("species") != self._last_notable.get("species"):
                sticky_dirty = True
            self._last_notable = notable[0]

        if sticky_dirty:
            await self._sticky_store.async_save(
                {"last_detected": self._last_detected, "last_notable": self._last_notable}
            )

        # Sticky-record bootstrap (quiet-hour fresh install / restart w/o store).
        if (self._last_detected is None or self._last_notable is None) and daily_count:
            bootstrap_dirty = False
            if self._last_detected is None:
                by_recency = sorted(daily_count, key=lambda x: x.get("last_seen") or "", reverse=True)
                if by_recency:
                    self._last_detected = by_recency[0]
                    bootstrap_dirty = True
            if self._last_notable is None:
                by_rarity = sorted(daily_count, key=lambda x: x.get("rarity_score", 0), reverse=True)
                if by_rarity:
                    self._last_notable = by_rarity[0]
                    bootstrap_dirty = True
            if bootstrap_dirty:
                await self._sticky_store.async_save(
                    {"last_detected": self._last_detected, "last_notable": self._last_notable}
                )

        recent_events = _build_recent_events(
            daily_raw,
            self._baseline_ranks,
            self._baseline_species_count,
            self._image_urls.get,
            LAST_DETECTION_EVENT_LIMIT,
        )

        self._fire_detection_events(detections, newly_seen, prior_last_seen)

        # Native per-period aggregates (activity / diversity / new-species /
        # history). Best-effort: a blip here leaves those sensors unknown rather
        # than failing the whole poll. BirdWeather's true counts make this far
        # simpler than Haikubox's local per-day store + backfill.
        try:
            overview = await self._client.get_overview(
                self.station_id,
                today=today,
                new_species_cutoff=today - timedelta(days=NEW_SPECIES_WINDOW_DAYS),
                baseline_days=ACTIVITY_BASELINE_DAYS,
            )
        except (aiohttp.ClientError, BirdWeatherError) as err:
            _LOGGER.warning("Could not fetch station overview: %s", err)
            overview = {}

        # Today's top species (true counts), enriched with the rarity baseline.
        # These records carry photo attribution from the API; fold it into the
        # cache so the baseline/new-species lists can show it for species that
        # only appear here (not in the recent detection feed).
        today_top = list(overview.get("today_top") or [])
        attr_dirty = False
        for rec in today_top:
            rec["last_seen"] = self._last_seen.get(rec["species"])
            if self._cache_image_attr(rec.get("sp_code", ""), rec):
                attr_dirty = True
        if attr_dirty:
            await self._image_attr_store.async_save(self._image_attr)
        _apply_rarity_scores(today_top, self._baseline_ranks, self._baseline_species_count)

        return {
            "recent_detections": _ranked(detections),
            "last_detection": self._last_detected,
            "recent_events": _ranked(recent_events),
            "notable_detection": self._last_notable,
            # The trailing-24h detection list still feeds the 7-day rarest
            # rollup, notability, and the extended-silence sensor. Distinct key
            # from the `daily_count` *sensor* (which shows today_total) — the
            # headline count/top-species come from true native totals.
            "detections_24h": daily_count,
            "daily_top_species": _ranked(today_top),
            "today_total": overview.get("today_total"),
            "today_top": today_top,
            "typical_daily_count": overview.get("typical_daily"),
            "new_species_window": overview.get("new_species_window"),
            "history_earliest": overview.get("history_earliest"),
            "notable_detections": _ranked(notable),
            "new_detections": _ranked(self._build_new_species_history()),
            "new_detection": self._build_last_new_species(),
            "lifetime_species_count": (
                overview.get("lifetime_species") or len(self._seen_species)
            ),
            "yearly_top_species": self._build_baseline_top(),
            "rarest_species": _ranked(seven_day_rare),
        }

    # ------------------------------------------------------------------
    # Automation events
    # ------------------------------------------------------------------

    def _fire_detection_events(
        self,
        detections: list[dict[str, Any]],
        newly_seen: set[str],
        prior_last_seen: dict[str, str],
    ) -> None:
        by_species = {d["species"]: d for d in detections if d.get("species")}
        current_recent = set(by_species)

        for sp in newly_seen:
            self._fire_event(TRIGGER_NEW_SPECIES, by_species[sp])

        if self._prev_recent_species is not None:
            threshold_days = self.config_entry.options.get(
                CONF_ABSENCE_DAYS, DEFAULT_ABSENCE_DAYS
            )
            now = datetime.now(timezone.utc)
            for sp in current_recent - self._prev_recent_species:
                if sp in newly_seen:
                    continue
                prior = _parse_dt(prior_last_seen.get(sp))
                if prior is None:
                    continue
                days_absent = (now - prior).days
                if days_absent >= threshold_days:
                    self._fire_event(
                        TRIGGER_UNUSUAL_VISITOR, by_species[sp], days_absent=days_absent
                    )

        # Watched species: fire when a user-chosen species enters the recent
        # window (edge-gated against the previous poll, like unusual_visitor, so
        # it fires on appearance — not every poll while it lingers). Silent on
        # the first poll of a session (prev is None → no restart flood). A
        # newly-seen species that's also watched fires both events — both true.
        watched = self._watched_species()
        if watched and self._prev_recent_species is not None:
            for sp in current_recent - self._prev_recent_species:
                if sp.casefold() in watched:
                    self._fire_event(TRIGGER_WATCHED_SPECIES, by_species[sp])

        self._prev_recent_species = current_recent

    def _watched_species(self) -> set[str]:
        """Case-folded set of common names to watch, from the options flow:
        the pick-list selections plus the free-text list (one name per line)."""
        opts = self.config_entry.options
        names = list(opts.get(CONF_WATCHED_SPECIES) or [])
        names += [ln.strip() for ln in (opts.get(CONF_WATCHED_EXTRA) or "").splitlines()]
        return {n.casefold() for n in names if n.strip()}

    @property
    def known_species(self) -> list[str]:
        """Species this station has been seen to detect (for the watch-list
        picker in the options flow), sorted alphabetically."""
        return sorted(self._seen_species)

    def _fire_event(self, trigger_type: str, record: dict[str, Any], **extra: Any) -> None:
        device = dr.async_get(self.hass).async_get_device(
            identifiers={(DOMAIN, self.station_id)}
        )
        if device is None:
            return
        self.hass.bus.async_fire(
            EVENT_BIRDWEATHER,
            {
                "device_id": device.id,
                "station_id": self.station_id,
                "device_name": self.device_name,
                "type": trigger_type,
                "species": record.get("species"),
                "scientific_name": record.get("scientific_name"),
                "sp_code": record.get("sp_code"),
                "image_url": record.get("image_url"),
                "audio_url": record.get("audio_url"),
                "confidence": record.get("confidence"),
                "last_seen": record.get("last_seen"),
                "rarity_score": record.get("rarity_score"),
                "yearly_rank": record.get("yearly_rank"),
                **extra,
            },
        )

    # ------------------------------------------------------------------
    # Store helpers
    # ------------------------------------------------------------------

    async def _load_stores(self) -> None:
        seen      = await self._store.async_load()
        sp_codes  = await self._sp_codes_store.async_load()
        sci_names = await self._sci_names_store.async_load()
        last_seen = await self._last_seen_store.async_load()
        images    = await self._images_store.async_load()
        image_attr = await self._image_attr_store.async_load()
        yearly    = await self._yearly_store.async_load()
        seven_day = await self._seven_day_store.async_load()
        sticky    = await self._sticky_store.async_load()

        self._seen_species   = seen      if isinstance(seen, dict)      else {}
        self._sp_codes       = sp_codes  if isinstance(sp_codes, dict)  else {}
        self._sci_names      = sci_names if isinstance(sci_names, dict) else {}
        self._last_seen      = last_seen if isinstance(last_seen, dict) else {}
        self._image_urls     = images    if isinstance(images, dict)    else {}
        self._image_attr     = image_attr if isinstance(image_attr, dict) else {}
        self._baseline_items   = yearly    if isinstance(yearly, list)    else []
        self._seven_day_data = seven_day if isinstance(seven_day, dict) else {}

        if isinstance(sticky, dict):
            ld = sticky.get("last_detected")
            ln = sticky.get("last_notable")
            if isinstance(ld, dict):
                self._last_detected = ld
            if isinstance(ln, dict):
                self._last_notable = ln

        self._baseline_ranks = {
            item["species"]: item["rank"]
            for item in self._baseline_items
            if isinstance(item, dict) and item.get("species") and item.get("rank")
        }
        self._baseline_species_count = len(self._baseline_ranks)

        self._stores_loaded = True

    async def _update_seven_day(
        self, detections: list[dict[str, Any]], today: date
    ) -> list[dict[str, Any]]:
        today_str = today.isoformat()
        today_map: dict[str, dict] = {
            item["species"]: item for item in self._seven_day_data.get(today_str, [])
        }

        dirty = False
        for d in detections:
            sp = d["species"]
            existing = today_map.get(sp)
            if existing is None or d.get("rarity_score", 0) >= existing.get("rarity_score", 0):
                today_map[sp] = {
                    "species": sp,
                    "sp_code": d.get("sp_code", ""),
                    "scientific_name": d.get("scientific_name", ""),
                    "rarity_score": d.get("rarity_score", 0.0),
                    "yearly_rank": d.get("yearly_rank", 0),
                    "count": d.get("count", 0),
                    "last_seen": d.get("last_seen"),
                }
                dirty = True

        self._seven_day_data[today_str] = list(today_map.values())

        cutoff = (today - timedelta(days=7)).isoformat()
        for k in [k for k in self._seven_day_data if k < cutoff]:
            del self._seven_day_data[k]
            dirty = True

        if dirty:
            await self._seven_day_store.async_save(self._seven_day_data)

        merged: dict[str, dict] = {}
        for day_items in self._seven_day_data.values():
            for item in day_items:
                sp = item["species"]
                existing = merged.get(sp)
                if existing is None or item.get("rarity_score", 0) >= existing.get("rarity_score", 0):
                    merged[sp] = dict(item)

        ordered = sorted(merged.values(), key=lambda x: x.get("rarity_score", 0), reverse=True)
        for rec in ordered:
            sp_code = rec.get("sp_code", "")
            rec["image_url"] = self._image_urls.get(sp_code)
            rec.update(self._image_attribution(sp_code))
        return ordered

    # ------------------------------------------------------------------
    # Dataset builders (store-only, no API calls)
    # ------------------------------------------------------------------

    def _cache_image_attr(self, sp_code: str, record: dict[str, Any]) -> bool:
        """Remember a species' photo credit/license (keyed by sp_code) so sticky
        and store-built records keep their attribution. Returns True if changed.
        """
        if not sp_code:
            return False
        attr = {k: record.get(k) for k in _ATTR_KEYS}
        if not any(attr.values()):  # nothing worth caching yet
            return False
        if self._image_attr.get(sp_code) != attr:
            self._image_attr[sp_code] = attr
            return True
        return False

    def _image_attribution(self, sp_code: str) -> dict[str, Any]:
        """Cached photo credit/license for a species code (None values if unknown)."""
        attr = self._image_attr.get(sp_code) or {}
        return {k: attr.get(k) for k in _ATTR_KEYS}

    def _build_baseline_top(self) -> list[dict[str, Any]]:
        result = []
        for item in self._baseline_items:
            sp = item["species"]
            sp_code = self._sp_codes.get(sp, "")
            result.append({
                **item,
                "sp_code": sp_code,
                "scientific_name": self._sci_names.get(sp, ""),
                "last_seen": self._last_seen.get(sp),
                "image_url": self._image_urls.get(sp_code),
                **self._image_attribution(sp_code),
            })
        return result

    def _build_new_species_history(self) -> list[dict[str, Any]]:
        if not self._seen_species:
            return []
        sorted_items = sorted(
            self._seen_species.items(), key=lambda kv: kv[1] or "", reverse=True
        )[:NEW_SPECIES_HISTORY_LIMIT]
        denom = max(self._baseline_species_count, 1)
        result: list[dict[str, Any]] = []
        for species, first_seen in sorted_items:
            sp_code = self._sp_codes.get(species, "")
            rank = self._baseline_ranks.get(species, self._baseline_species_count)
            result.append({
                "species": species,
                "scientific_name": self._sci_names.get(species, ""),
                "sp_code": sp_code,
                "image_url": self._image_urls.get(sp_code),
                "last_seen": self._last_seen.get(species),
                "first_seen": first_seen,
                "rarity_score": round(rank / denom, 4),
                "yearly_rank": rank,
                **self._image_attribution(sp_code),
            })
        return result

    def _build_last_new_species(self) -> dict[str, Any] | None:
        history = self._build_new_species_history()
        return history[0] if history else None

    # ------------------------------------------------------------------
    # Public properties (diagnostics)
    # ------------------------------------------------------------------

    @property
    def baseline_fetched_date(self) -> date | None:
        return self._baseline_fetched_date

    @property
    def baseline_species_count(self) -> int:
        return self._baseline_species_count

    @property
    def lifetime_species_count(self) -> int:
        return len(self._seen_species)


# ------------------------------------------------------------------
# Response normalisation (Haikubox pipeline, BirdWeather raw keys)
# ------------------------------------------------------------------

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
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


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


# Photo credit/license keys threaded from the client onto every record so the
# cards can show attribution (CC BY-SA images require it).
_ATTR_KEYS = ("image_credit", "image_credit_url", "image_license", "image_license_url")


def _normalise_detections(raw: Any) -> list[dict[str, Any]]:
    """Collapse the flat event list to one record per species, newest first.

    Image URLs come straight from the API (`image`); the latest event's
    `confidence`/`audio` ride along on the per-species record.
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
                "image_url": item.get("image"),
                "last_seen": dt_str,
                "_last_seen_dt": parsed,
                "audio_url": item.get("audio"),
                "confidence": item.get("confidence"),
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
            rec["audio_url"] = item.get("audio")
            rec["confidence"] = item.get("confidence")
            if item.get("image"):
                rec["image_url"] = item.get("image")

    results = sorted(
        by_species.values(),
        key=lambda x: x.get("_last_seen_dt") or datetime.min.replace(tzinfo=timezone.utc),
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
            "image_url": item.get("image") or image_url_for(sp_code),
            "last_seen": dt_str,
            "audio_url": item.get("audio"),
            "confidence": item.get("confidence"),
            "rarity_score": round(rank / denom, 4),
            "yearly_rank": rank,
            **{k: item.get(k) for k in _ATTR_KEYS},
        })
    events.sort(key=lambda e: e.get("last_seen") or "", reverse=True)
    return events[:limit]
