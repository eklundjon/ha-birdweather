from __future__ import annotations

import inspect
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import API_BATS, API_BIRDS, BAT, BIRD, BirdWeatherClient, BirdWeatherError
from .const import (
    ACTIVITY_BASELINE_DAYS,
    BAT_ACTIVITY_QUIET_MINUTES,
    BAT_FETCH_LIMIT,
    CONF_ABSENCE_DAYS,
    CONF_ALERT_MIN_CONFIDENCE,
    CONF_AUDIO_ENABLED,
    CONF_BAT_SUPPORT,
    CONF_FEED_MIN_CONFIDENCE,
    CONF_NEW_SPECIES_WINDOW_DAYS,
    CONF_NOTABLE_RARITY_WEIGHT,
    CONF_RARITY_PERIOD_MONTHS,
    CONF_RECENT_WINDOW_HOURS,
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_WATCHED_EXTRA,
    CONF_WATCHED_SPECIES,
    DAILY_WINDOW_HOURS,
    DEFAULT_ABSENCE_DAYS,
    DEFAULT_ALERT_MIN_CONFIDENCE,
    DEFAULT_AUDIO_ENABLED,
    DEFAULT_BAT_SUPPORT,
    DEFAULT_FEED_MIN_CONFIDENCE,
    DEFAULT_NOTABLE_RARITY_WEIGHT,
    DEFAULT_SCAN_INTERVAL,
    DETECTION_FETCH_LIMIT,
    DIEL_WINDOW_DAYS,
    DOMAIN,
    EVENT_BIRDWEATHER,
    LAST_DETECTION_EVENT_LIMIT,
    NEW_SPECIES_HISTORY_LIMIT,
    NEW_SPECIES_WINDOW_DAYS,
    NOTABILITY_WINDOW_HOURS,
    RARITY_PERIOD_MONTHS,
    RECENT_WINDOW_HOURS,
    TRIGGER_BAT_ACTIVITY,
    TRIGGER_NEW_SPECIES,
    TRIGGER_UNUSUAL_VISITOR,
    TRIGGER_WATCHED_SPECIES,
)
from .normalize import (
    _ATTR_KEYS,
    _allaboutbirds_url,
    _apply_notability_scores,
    _apply_rarity_scores,
    _build_recent_events,
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
from .statistics import async_import_history_statistics

_LOGGER = logging.getLogger(__name__)

# UpdateFailed(retry_after=...) delays the next refresh (Home Assistant 2025.12+).
# Older versions don't accept the argument, so check once.
_UPDATE_FAILED_TAKES_RETRY_AFTER = (
    "retry_after" in inspect.signature(UpdateFailed.__init__).parameters
)


def _update_failed(message: str, retry_after: float | None) -> UpdateFailed:
    """UpdateFailed carrying retry_after where this Home Assistant supports it."""
    if retry_after is not None and _UPDATE_FAILED_TAKES_RETRY_AFTER:
        return UpdateFailed(message, retry_after=retry_after)
    return UpdateFailed(message)


def async_get_entry_device(
    hass: HomeAssistant, identifier: tuple[str, str], entry_id: str
) -> dr.DeviceEntry | None:
    """The entry's device with this identifier, or None.

    device_registry.async_get_device is deprecated from 2026.9 (identifiers
    are unique per config entry now) and breaks in 2027.8. Its replacement
    doesn't exist before 2026.8, so fall back on older versions.
    """
    reg = dr.async_get(hass)
    if hasattr(reg, "async_get_device_by_identifier"):
        return reg.async_get_device_by_identifier(identifier, entry_id)
    return reg.async_get_device(identifiers={identifier})

_STORE_VERSION = 1

# Per-station .storage suffixes — the live set, removed when the entry is removed
# (see async_remove_stores). Keep in sync with the Store(...) creation in __init__.
_STORE_SUFFIXES = (
    "seen_species",
    "last_seen",
    "yearly",
    "seven_day",
    "recent_events",
    "species_meta",
    "last_by_class",
)

# Legacy per-station stores from earlier versions: the five cold maps now folded
# into species_meta, plus the old .sticky (now the event buffer + live notable).
# Migrated/cleaned on load and also removed on entry removal.
_LEGACY_STORE_SUFFIXES = (
    "sp_codes",
    "sci_names",
    "image_urls",
    "image_attr",
    "links",
    "sticky",
)
# Keys of the consolidated species_meta store, in (key, in-memory attr) form.
_META_KEYS = ("sp_codes", "sci_names", "image_urls", "image_attr", "links")

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
        station_id = entry.data[CONF_STATION_ID]
        # Poll interval is user-tunable (minutes); an options change reloads the
        # entry, so a new interval takes effect via this fresh coordinator.
        scan_minutes = entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL // 60
        )
        super().__init__(
            hass,
            _LOGGER,
            # Include the station id so log lines disambiguate which station they
            # refer to when more than one is configured.
            name=f"{DOMAIN} {station_id}",
            config_entry=entry,
            update_interval=timedelta(minutes=scan_minutes),
        )
        self.station_id = station_id
        self.device_name = entry.data.get(CONF_STATION_NAME, "BirdWeather Station")
        self._session = async_get_clientsession(hass)
        self._client = BirdWeatherClient(self._session)

        # Rarity baseline (topSpecies counts) — refreshed once per calendar day.
        self._baseline_ranks: dict[str, int] = {}
        self._baseline_species_count: int = 0
        self._baseline_fetched_date: date | None = None
        self._baseline_available = False

        # Diel activity (time-of-day histogram) — a slow-changing daily rhythm,
        # so refreshed once per calendar day. `by_species` maps common name → a
        # 24-bucket hourly count array; `station` is the summed station-wide curve.
        self._diel_by_species: dict[str, list[int]] = {}
        self._diel_station: list[int] = []
        self._diel_fetched_date: date | None = None

        # Long-term statistics backfill — imported once per calendar day.
        self._stats_imported_date: date | None = None

        # Rolling buffer of the most-recent detection EVENTS (newest-first,
        # capped at LAST_DETECTION_EVENT_LIMIT), persisted. This backs
        # last_detection: "the last detection" is the last detection no matter
        # how old, so it must NOT drain when the live feed empties (station
        # offline). The buffer survives restarts and outages; its head is the
        # last_detection state. notable_species is deliberately NOT sticky — it's
        # "notable observed in the last 24 h", so it drains with its window.
        self._event_buffer: list[dict[str, Any]] = []

        # Bat support (entry data, changed via reconfigure, which reloads). Off:
        # bats aren't even fetched. On: they come from their own class-filtered
        # feed and get their own sensors and events. The bird feed and every
        # bird figure are filtered to BirdWeather's avian class either way.
        self._bat_support: bool = entry.data.get(CONF_BAT_SUPPORT, DEFAULT_BAT_SUPPORT)
        # The newest bird and newest bat event, persisted on their own: the
        # shared event buffer can be a single night of bats, so deriving
        # last_bird_detection from it would lose the bird after a restart.
        self._last_by_class: dict[str, dict[str, Any] | None] = {BIRD: None, BAT: None}
        # Bats in the recent window on the previous poll (watched_species edge).
        self._prev_recent_bats: set[str] | None = None

        # Persistent stores
        self._store           = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.seen_species")
        self._last_seen_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.last_seen")
        self._yearly_store     = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.yearly")
        self._seven_day_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.seven_day")
        self._events_store     = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.recent_events")
        # The five cold per-species lookup maps (sp_codes, sci_names, image_urls,
        # image_attr, links) change together (when a new species is first seen)
        # and are static otherwise, so they share one store rather than five —
        # fewer files and one write instead of five. They stay separate dicts in
        # memory; only persistence is consolidated. (Migrated from the old
        # per-map stores on first load — see _load_stores.)
        self._meta_store       = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.species_meta")
        self._by_class_store   = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.last_by_class")

        # In-memory store state
        self._seen_species: dict[str, str] = {}       # species → first_seen ISO
        self._sp_codes: dict[str, str] = {}           # species → sp_code
        self._sci_names: dict[str, str] = {}          # species → scientific_name
        self._last_seen: dict[str, str] = {}          # species → last_seen ISO
        self._image_urls: dict[str, str] = {}         # sp_code → image URL
        # sp_code → {image_credit, image_credit_url, image_license, image_license_url}
        self._image_attr: dict[str, dict[str, Any]] = {}
        # sp_code → {ebird_url, wikipedia_url} (upstream URLs BirdWeather supplies)
        self._links_cache: dict[str, dict[str, Any]] = {}
        # Bats seen, by name → {scientific_name, image_url, wikipedia_url,
        # birdweather_url, photo attribution}. Bats have no eBird code, which is
        # what the maps above are keyed by, so they keep their own. Also how a
        # name in _seen_species is known to be a bat.
        self._bats: dict[str, dict[str, Any]] = {}
        self._baseline_items: list[dict[str, Any]] = []
        self._seven_day_data: dict[str, list] = {}

        # unusual_visitor edge detection (None until first poll baselines).
        self._prev_recent_species: set[str] | None = None

    # ------------------------------------------------------------------
    # DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_setup(self) -> None:
        """One-time setup before the first refresh: rehydrate persisted stores,
        and decide bat support for an entry set up before it existed."""
        await self._load_stores()
        if CONF_BAT_SUPPORT not in self.config_entry.data:
            await self._async_decide_bat_support()

    async def _async_decide_bat_support(self) -> None:
        """One-time choice for an entry set up before bat support existed.

        Such a station has been counting any bats it hears as birds, so turn
        bat support on if BirdWeather says it hears bats, and save the answer
        either way so this never runs again (or overrides a later choice made
        in reconfigure). Runs during the first refresh, before the platforms
        set up and before the update listener is attached, so the bat sensors
        appear on this same start without a reload. If BirdWeather can't be
        reached, nothing is saved and it's tried again next start.
        """
        try:
            found = await self._client.station_has_bats(self.station_id)
        except (aiohttp.ClientError, BirdWeatherError) as err:
            _LOGGER.debug("Could not check the station for bats: %s", err)
            return
        self._bat_support = found
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={**self.config_entry.data, CONF_BAT_SUPPORT: found},
        )
        if found:
            _LOGGER.info(
                "%s hears bats, so bat support is now on; turn it off with "
                "Reconfigure if you don't want it",
                self.device_name,
            )

    def _merge_event_buffer(self, poll_events: list[dict[str, Any]]) -> bool:
        """Merge this poll's events into the rolling last-N buffer that backs
        last_detection. De-duped by (sp_code, last_seen), newest-first, capped at
        LAST_DETECTION_EVENT_LIMIT. Returns whether the buffer changed (→ persist).
        """
        existing = {(e.get("sp_code"), e.get("last_seen")) for e in self._event_buffer}
        added = False
        for ev in poll_events:
            key = (ev.get("sp_code"), ev.get("last_seen"))
            if ev.get("last_seen") and key not in existing:
                self._event_buffer.append(dict(ev))
                existing.add(key)
                added = True
        if added:
            self._event_buffer.sort(key=lambda e: e.get("last_seen") or "", reverse=True)
            del self._event_buffer[LAST_DETECTION_EVENT_LIMIT:]
        return added

    def _buffer_view(self, audio_enabled: bool) -> list[dict[str, Any]]:
        """Display copies of the event buffer for last_detection: fresh image_url
        (a species' photo may have been cached after the event was buffered) and
        current rarity scores, without mutating the stored buffer. audio_url is
        gated on the current audio_enabled option so toggling audio off hides the
        play button; _with_links (applied by the caller) stamps reference links."""
        view = [dict(e) for e in self._event_buffer]
        for e in view:
            # Events buffered before bat support existed carry no classification.
            e.setdefault("classification", BIRD)
            img = self._image_urls.get(e.get("sp_code"))
            if img:
                e["image_url"] = img
            if not audio_enabled:
                e["audio_url"] = None
        _apply_rarity_scores(view, self._baseline_ranks, self._baseline_species_count)
        return view

    async def _save_meta(self) -> None:
        """Persist the cold per-species maps as one species_meta store."""
        await self._meta_store.async_save({
            "sp_codes": self._sp_codes,
            "sci_names": self._sci_names,
            "image_urls": self._image_urls,
            "image_attr": self._image_attr,
            "links": self._links_cache,
            "bats": self._bats,
        })

    @staticmethod
    async def async_remove_stores(hass: HomeAssistant, station_id: str) -> None:
        """Delete this station's persistent .storage files (live + legacy).

        Called from async_remove_entry when the integration entry is removed.
        Store.async_remove() no-ops if a file is already gone."""
        for suffix in (*_STORE_SUFFIXES, *_LEGACY_STORE_SUFFIXES):
            await Store(
                hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.{suffix}"
            ).async_remove()

    async def _async_update_data(self) -> dict[str, Any]:

        # UTC-anchored day boundaries (matches the pipeline's assumptions).
        today = datetime.now(UTC).date()

        # Refresh the rarity baseline once per calendar day.
        if self._baseline_fetched_date != today:
            rarity_months = self.config_entry.options.get(
                CONF_RARITY_PERIOD_MONTHS, RARITY_PERIOD_MONTHS
            )
            try:
                baseline_raw = await self._client.get_baseline_count(
                    self.station_id, months=rarity_months
                )
                self._baseline_ranks, self._baseline_species_count, self._baseline_items = (
                    _process_baseline_count(baseline_raw)
                )
                self._baseline_fetched_date = today
                self._baseline_available = True
                await self._yearly_store.async_save(self._baseline_items)
            except (aiohttp.ClientError, BirdWeatherError) as err:
                _LOGGER.warning("Could not fetch rarity baseline: %s", err)

        if not self._baseline_available:
            raise UpdateFailed(
                "Rarity baseline not yet available: topSpecies fetch failed on "
                "first poll and there is no cached baseline"
            )

        # Refresh the diel activity histogram once per calendar day (best-effort;
        # a blip leaves the prior curve in place rather than failing the poll).
        if self._diel_fetched_date != today:
            try:
                diel = await self._client.get_time_of_day(
                    self.station_id, days=DIEL_WINDOW_DAYS
                )
                self._diel_by_species = diel["by_species"]
                self._diel_station = diel["station"]
                self._diel_fetched_date = today
            except (aiohttp.ClientError, BirdWeatherError) as err:
                _LOGGER.warning("Could not fetch time-of-day activity: %s", err)

        try:
            raw_all = await self._client.get_raw_detections(
                self.station_id, first=DETECTION_FETCH_LIMIT, classifications=[API_BIRDS]
            )
        except (aiohttp.ClientError, BirdWeatherError) as err:
            raise _update_failed(
                f"Error communicating with BirdWeather API: {err}", self._retry_after(err)
            ) from err

        # Bats come from their own feed, so they can't crowd birds out of the
        # bird feed's limit (or vice versa). Best-effort: a blip leaves the bat
        # data as it was rather than failing the poll.
        bat_all: dict[str, Any] = {"detections": []}
        if self._bat_support:
            try:
                bat_all = await self._client.get_raw_detections(
                    self.station_id, first=BAT_FETCH_LIMIT, classifications=[API_BATS]
                )
            except (aiohttp.ClientError, BirdWeatherError) as err:
                _LOGGER.warning("Could not fetch bat detections: %s", err)
        # No audio for bats yet: their ultrasonic clips need processing to be
        # audible, which is planned separately.
        for item in bat_all["detections"]:
            item["audio"] = None

        # Feed min-confidence: drop low-confidence "maybe" events before any
        # windowing, so every feed-derived sensor + alert sees only the kept
        # set. The native count/diversity/activity aggregates come from the
        # server (get_overview) and reflect the station's own minConfidence —
        # this filter does not, and cannot, reduce those.
        feed_min = self.config_entry.options.get(
            CONF_FEED_MIN_CONFIDENCE, DEFAULT_FEED_MIN_CONFIDENCE
        )
        if feed_min:
            raw_all["detections"] = _filter_by_confidence(
                raw_all.get("detections", []), feed_min
            )
            bat_all["detections"] = _filter_by_confidence(bat_all["detections"], feed_min)

        now = datetime.now(UTC)
        # The fetch returns the most-recent N events regardless of age; carve
        # the trailing 24h (and the 1h subset) out of it client-side. Busy
        # stations may exhaust the limit inside 24h — see DETECTION_FETCH_LIMIT.
        recent_hours = self.config_entry.options.get(
            CONF_RECENT_WINDOW_HOURS, RECENT_WINDOW_HOURS
        )
        daily_raw = {"detections": _filter_by_dt(raw_all, now - timedelta(hours=DAILY_WINDOW_HOURS))}
        recent_raw = {"detections": _filter_by_dt(daily_raw, now - timedelta(hours=recent_hours))}
        bat_daily_raw = {"detections": _filter_by_dt(bat_all, now - timedelta(hours=DAILY_WINDOW_HOURS))}
        bat_recent_raw = {"detections": _filter_by_dt(bat_daily_raw, now - timedelta(hours=recent_hours))}

        # Master switch for "play the call" (opt-in; off by default). When off,
        # audio_url is never surfaced, so the cards render no play button.
        audio_enabled = self.config_entry.options.get(
            CONF_AUDIO_ENABLED, DEFAULT_AUDIO_ENABLED
        )

        detections = _normalise_detections(recent_raw, audio_enabled)
        _apply_rarity_scores(detections, self._baseline_ranks, self._baseline_species_count)

        daily_count = sorted(
            _normalise_detections(daily_raw, audio_enabled),
            key=lambda x: x.get("count", 0),
            reverse=True,
        )
        _apply_rarity_scores(daily_count, self._baseline_ranks, self._baseline_species_count)

        # Cache the upstream eBird/Wikipedia URLs BirdWeather supplies, keyed by
        # sp_code and persisted, so store-built lists (watch-list, baseline,
        # new-species) keep links for species not heard this session. eBird
        # falls back to a template; Wikipedia has no template, so this is its
        # only source.
        # The five cold per-species maps share one species_meta store; meta_dirty
        # tracks a change to any of them across the whole poll and they're saved
        # once, below, after the last one (today_top) is updated.
        meta_dirty = False
        for item in daily_raw["detections"]:
            code = item.get("spCode") or ""
            if not code:
                continue
            links = {
                "ebird_url": item.get("ebird_url"),
                "wikipedia_url": item.get("wikipedia_url"),
                "birdweather_url": item.get("birdweather_url"),
                "alpha": item.get("alpha"),
                "alpha6": item.get("alpha6"),
            }
            if any(links.values()) and self._links_cache.get(code) != links:
                self._links_cache[code] = links
                meta_dirty = True

        # Snapshot last_seen before the update loop (for absence-gap measuring).
        prior_last_seen = dict(self._last_seen)

        # Update sp_codes / scientific_name / last_seen / image lookups.
        last_seen_dirty = False
        for d in detections:
            sp = d["species"]
            if d.get("sp_code") and sp not in self._sp_codes:
                self._sp_codes[sp] = d["sp_code"]
                meta_dirty = True
            if d.get("scientific_name") and sp not in self._sci_names:
                self._sci_names[sp] = d["scientific_name"]
                meta_dirty = True
            if d.get("sp_code") and d.get("image_url"):
                if self._image_urls.get(d["sp_code"]) != d["image_url"]:
                    self._image_urls[d["sp_code"]] = d["image_url"]
                    meta_dirty = True
            if self._cache_image_attr(d.get("sp_code", ""), d):
                meta_dirty = True
            ts = d.get("last_seen")
            if ts and ts > self._last_seen.get(sp, ""):
                self._last_seen[sp] = ts
                last_seen_dirty = True

        seen_dirty = False
        # Captured before the bootstrap below seeds it, so bats seed too.
        fresh_install = not self._seen_species

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
                        meta_dirty = True
                    if d.get("image_url") and self._image_urls.get(d["sp_code"]) != d["image_url"]:
                        self._image_urls[d["sp_code"]] = d["image_url"]
                        meta_dirty = True
                if self._cache_image_attr(d.get("sp_code", ""), d):
                    meta_dirty = True
                if d.get("scientific_name") and sp not in self._sci_names:
                    self._sci_names[sp] = d["scientific_name"]
                    meta_dirty = True
                ts = d.get("last_seen")
                if ts and ts > self._last_seen.get(sp, ""):
                    self._last_seen[sp] = ts
                    last_seen_dirty = True
                self._seen_species[sp] = (
                    first_seen_by_species.get(sp) or d.get("last_seen") or today.isoformat()
                )
                seen_dirty = True

        # Bats: remember each one's name, photo and links (that's also how a
        # name is known to be a bat), track last-seen, and on a fresh install
        # seed the first-seen log like the birds above.
        for item in bat_daily_raw["detections"]:
            sp = item.get("cn")
            if not sp:
                continue
            meta = {
                "scientific_name": item.get("sn") or "",
                "image_url": item.get("image"),
                "wikipedia_url": item.get("wikipedia_url"),
                "birdweather_url": item.get("birdweather_url"),
                **{k: item.get(k) for k in _ATTR_KEYS},
            }
            if self._bats.get(sp) != meta:
                self._bats[sp] = meta
                meta_dirty = True
        bat_first_seen = _first_seen_per_species(bat_daily_raw) if fresh_install else {}
        for d in _normalise_detections(bat_daily_raw, audio_enabled=False):
            sp = d["species"]
            ts = d.get("last_seen")
            if ts and ts > self._last_seen.get(sp, ""):
                self._last_seen[sp] = ts
                last_seen_dirty = True
            if fresh_install and sp not in self._seen_species:
                self._seen_species[sp] = bat_first_seen.get(sp) or ts or today.isoformat()
                seen_dirty = True

        if last_seen_dirty:
            await self._last_seen_store.async_save(self._last_seen)

        # Live new-species detection from the recent window.
        newly_seen: set[str] = set()
        for d in detections:
            sp = d["species"]
            if sp not in self._seen_species:
                self._seen_species[sp] = d.get("last_seen") or today.isoformat()
                newly_seen.add(sp)
                seen_dirty = True
        # The same for bats in the recent window (empty without bat support).
        bat_recent = _normalise_detections(bat_recent_raw, audio_enabled=False)
        newly_seen_bats: set[str] = set()
        for d in bat_recent:
            sp = d["species"]
            if sp and sp not in self._seen_species:
                self._seen_species[sp] = d.get("last_seen") or today.isoformat()
                newly_seen_bats.add(sp)
                seen_dirty = True
        if seen_dirty:
            await self._store.async_save(self._seen_species)

        seven_day_rare = await self._update_seven_day(daily_count, today)

        # Notability: weighted blend of rarity + recency over the 24h list.
        # notable is deliberately NOT sticky — it drains with its 24h window, so
        # notable_detection is the current top, or None when the window is empty
        # (station quiet/offline) → sensor "unknown". (#62)
        rarity_weight = self.config_entry.options.get(
            CONF_NOTABLE_RARITY_WEIGHT, DEFAULT_NOTABLE_RARITY_WEIGHT
        ) / 100.0
        _apply_notability_scores(daily_count, now, NOTABILITY_WINDOW_HOURS, rarity_weight)
        notable = sorted(daily_count, key=lambda x: x.get("notability_score", 0), reverse=True)

        # last_detection is backed by a persisted rolling buffer of recent EVENTS
        # (per-event, newest-first, capped), NOT the live feed — so "the last
        # detection" persists across restarts and outages (#62). Build this
        # poll's events, merge the new ones in, and persist when it changes.
        # With bat support on, the buffer (and so last_detection) takes birds
        # and bats alike; each event carries its classification.
        poll_events = _build_recent_events(
            {"detections": daily_raw["detections"] + bat_daily_raw["detections"]},
            self._baseline_ranks,
            self._baseline_species_count,
            self._image_urls.get,
            LAST_DETECTION_EVENT_LIMIT,
            audio_enabled,
        )
        if self._merge_event_buffer(poll_events):
            await self._events_store.async_save(self._event_buffer)

        # The newest bird and bats, each from its own feed: the mixed list above
        # is capped at the newest events, which on a busy morning are all birds
        # (and on a busy night all bats).
        bird_head = _build_recent_events(
            daily_raw, self._baseline_ranks, self._baseline_species_count,
            self._image_urls.get, 1, audio_enabled,
        )
        bat_events = _build_recent_events(
            bat_daily_raw, self._baseline_ranks, self._baseline_species_count,
            self._image_urls.get, LAST_DETECTION_EVENT_LIMIT, False,
        )
        prior_bat = self._last_by_class[BAT]
        if self._update_last_by_class(bird_head + bat_events):
            await self._by_class_store.async_save(self._last_by_class)

        self._fire_detection_events(detections, newly_seen, prior_last_seen)
        if self._bat_support:
            self._fire_bat_events(bat_recent, newly_seen_bats, bat_events, prior_bat)

        # Native per-period aggregates (activity / diversity / new-species /
        # history). Best-effort: a blip here leaves those sensors unknown rather
        # than failing the whole poll. BirdWeather's true counts make this far
        # simpler than Haikubox's local per-day store + backfill.
        try:
            overview = await self._client.get_overview(
                self.station_id,
                today=today,
                new_species_cutoff=today - timedelta(
                    days=self.config_entry.options.get(
                        CONF_NEW_SPECIES_WINDOW_DAYS, NEW_SPECIES_WINDOW_DAYS
                    )
                ),
                baseline_days=ACTIVITY_BASELINE_DAYS,
            )
        except (aiohttp.ClientError, BirdWeatherError) as err:
            _LOGGER.warning("Could not fetch station overview: %s", err)
            overview = {}

        # Onboard PUC hardware sensors (best-effort). Null sub-suites on a
        # station without that hardware → the sensor platform creates no
        # entities for them. A blip here leaves the readings stale rather than
        # failing the poll. The values themselves are stamped onto data so the
        # hardware entities (conditionally created from the first refresh) read
        # them; suite presence is what gates entity creation.
        try:
            sensors = await self._client.get_sensors(self.station_id)
        except (aiohttp.ClientError, BirdWeatherError) as err:
            _LOGGER.warning("Could not fetch station sensors: %s", err)
            sensors = {}

        # Backfill HA long-term statistics with the station's true daily history
        # (once per calendar day; idempotent). Needs the recorder + the history
        # start from the overview. No recorder → skip cleanly for the day.
        if self._stats_imported_date != today:
            if "recorder" not in (self.hass.config.components if self.hass else ()):
                self._stats_imported_date = today
            elif overview.get("history_earliest"):
                try:
                    await self._import_history_statistics(today, overview["history_earliest"])
                    self._stats_imported_date = today
                except (aiohttp.ClientError, BirdWeatherError) as err:
                    _LOGGER.warning("Could not import history statistics: %s", err)

        # Today's top species (true counts), enriched with the rarity baseline.
        # These records carry photo attribution from the API; fold it into the
        # cache so the baseline/new-species lists can show it for species that
        # only appear here (not in the recent detection feed).
        today_top = list(overview.get("today_top") or [])
        for rec in today_top:
            rec["last_seen"] = self._last_seen.get(rec["species"])
            if self._cache_image_attr(rec.get("sp_code", ""), rec):
                meta_dirty = True
        # today_top is the last writer of the cold maps this poll, so persist the
        # consolidated species_meta store once here for all of them.
        if meta_dirty:
            await self._save_meta()
        _apply_rarity_scores(today_top, self._baseline_ranks, self._baseline_species_count)

        # last_detection's head + list come from the persisted event buffer (not
        # the live feed), so they never drain on an outage (#62). notable stays
        # live — head + list drain to None / [] with the 24h window.
        recent_events_out = _ranked(self._with_links(self._buffer_view(audio_enabled)))
        notable_out = _ranked(self._with_links(notable))

        # Stamp reference-link URLs (eBird/Wikipedia/All About Birds) onto every
        # card-facing list, so the cards render links without constructing URLs.
        return {
            "recent_detections": _ranked(self._with_links(detections)),
            "last_detection": recent_events_out[0] if recent_events_out else None,
            "recent_events": recent_events_out,
            "notable_detection": notable_out[0] if notable_out else None,
            # The trailing-24h detection list still feeds the 7-day rarest
            # rollup, notability, and the extended-silence sensor. Distinct key
            # from the `daily_count` *sensor* (which shows today_total) — the
            # headline count/top-species come from true native totals.
            "detections_24h": daily_count,
            "daily_top_species": _ranked(self._with_links(today_top)),
            "today_total": overview.get("today_total"),
            "today_top": today_top,
            "typical_daily_count": overview.get("typical_daily"),
            "new_species_window": overview.get("new_species_window"),
            "history_earliest": overview.get("history_earliest"),
            "notable_detections": notable_out,
            "new_detections": _ranked(self._with_links(self._build_new_species_history())),
            "new_detection": self._build_last_new_species(),
            "lifetime_species_count": (
                overview.get("lifetime_species") or self.lifetime_species_count
            ),
            "yearly_top_species": self._with_links(self._build_baseline_top()),
            "rarest_species": _ranked(self._with_links(seven_day_rare)),
            "watched_species": _ranked(self._with_links(self._build_watched())),
            "sensors": sensors,
            # Diel activity (trailing 7-day, station-wide): the hourly curve for a
            # chart card + the peak hour for the "Peak activity hour" sensor.
            "hourly_activity": self._diel_station or None,
            "peak_activity_hour": _peak_hour(self._diel_station),
            # Bat sensors (only created with bat support on; the keys are always
            # present so turning it on needs no other change).
            "last_bird_detection": self._class_head(BIRD),
            "last_bat_detection": self._class_head(BAT),
            "bat_today_total": overview.get("bat_today_total", 0) if self._bat_support else 0,
            "bats_today": (
                _ranked(self._with_links(self._build_bats_today(overview)))
                if self._bat_support else []
            ),
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

        # Alert min-confidence gate (independent of the feed filter): suppress a
        # trigger when its detection is below the bar. Lets a user keep maybes in
        # the feed (feed filter low/off) while only being pinged on confident
        # hits. No-op at 0. Records with no numeric confidence are not alertable
        # once the gate is on (can't confirm they clear the bar).
        alert_min = self.config_entry.options.get(
            CONF_ALERT_MIN_CONFIDENCE, DEFAULT_ALERT_MIN_CONFIDENCE
        ) / 100.0

        def _alertable(record: dict[str, Any]) -> bool:
            if alert_min <= 0:
                return True
            c = record.get("confidence")
            return isinstance(c, (int, float)) and c >= alert_min

        for sp in newly_seen:
            if _alertable(by_species[sp]):
                self._fire_event(
                    TRIGGER_NEW_SPECIES,
                    by_species[sp],
                    lifetime_species_count=self.lifetime_species_count,
                )

        if self._prev_recent_species is not None:
            threshold_days = self.config_entry.options.get(
                CONF_ABSENCE_DAYS, DEFAULT_ABSENCE_DAYS
            )
            now = datetime.now(UTC)
            for sp in current_recent - self._prev_recent_species:
                if sp in newly_seen:
                    continue
                prior = _parse_dt(prior_last_seen.get(sp))
                if prior is None:
                    continue
                days_absent = (now - prior).days
                if days_absent >= threshold_days and _alertable(by_species[sp]):
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
                if sp.casefold() in watched and _alertable(by_species[sp]):
                    self._fire_event(TRIGGER_WATCHED_SPECIES, by_species[sp])

        self._prev_recent_species = current_recent

    def _fire_bat_events(
        self,
        bat_recent: list[dict[str, Any]],
        newly_seen_bats: set[str],
        bat_events: list[dict[str, Any]],
        prior_bat: dict[str, Any] | None,
    ) -> None:
        """Fire this poll's bat events: new_species and watched_species exactly
        as for birds, and bat_activity when bats are heard after at least
        BAT_ACTIVITY_QUIET_MINUTES without one. Bats aren't rarity-ranked, so
        there's no unusual_visitor for them. `bat_events` is this poll's bat
        events; `prior_bat` is the newest bat event as it was before this poll.
        Identification confidence gates them like bird alerts."""
        alert_min = self.config_entry.options.get(
            CONF_ALERT_MIN_CONFIDENCE, DEFAULT_ALERT_MIN_CONFIDENCE
        ) / 100.0

        def _alertable(record: dict[str, Any]) -> bool:
            if alert_min <= 0:
                return True
            c = record.get("confidence")
            return isinstance(c, (int, float)) and c >= alert_min

        by_species = {d["species"]: d for d in bat_recent if d.get("species")}
        bat_species_seen = sum(1 for sp in self._seen_species if self._is_bat(sp))
        for sp in newly_seen_bats:
            if _alertable(by_species[sp]):
                self._fire_event(
                    TRIGGER_NEW_SPECIES, by_species[sp], lifetime_species_count=bat_species_seen
                )

        current = set(by_species)
        watched = self._watched_species()
        if watched and self._prev_recent_bats is not None:
            for sp in current - self._prev_recent_bats:
                if sp.casefold() in watched and _alertable(by_species[sp]):
                    self._fire_event(TRIGGER_WATCHED_SPECIES, by_species[sp])
        self._prev_recent_bats = current

        # No previous bat (first run, or bats newly enabled): nothing to measure
        # a quiet spell against, so this poll only establishes the baseline.
        prior_dt = _parse_dt(prior_bat.get("last_seen")) if prior_bat else None
        if prior_dt is None:
            return
        new_bats = [
            ev for ev in bat_events
            if (dt := _parse_dt(ev.get("last_seen"))) is not None and dt > prior_dt
        ]
        if not new_bats:
            return
        first = min(_parse_dt(ev["last_seen"]) for ev in new_bats)
        quiet = first - prior_dt
        if quiet >= timedelta(minutes=BAT_ACTIVITY_QUIET_MINUTES):
            newest = max(new_bats, key=lambda ev: _parse_dt(ev["last_seen"]))
            if _alertable(newest):
                self._fire_event(
                    TRIGGER_BAT_ACTIVITY,
                    newest,
                    count=len(new_bats),
                    quiet_minutes=int(quiet.total_seconds() // 60),
                )

    def _update_last_by_class(self, events: list[dict[str, Any]]) -> bool:
        """Keep the newest bird and newest bat event, given candidates tagged
        with their classification. Returns whether either changed (→ persist)."""
        changed = False
        for cls in (BIRD, BAT):
            stored = self._last_by_class[cls]
            stored_dt = _parse_dt(stored.get("last_seen")) if stored else None
            for ev in events:
                if ev.get("classification", BIRD) != cls:
                    continue
                dt = _parse_dt(ev.get("last_seen"))
                if dt is not None and (stored_dt is None or dt > stored_dt):
                    stored = dict(ev)
                    stored_dt = dt
                    changed = True
            self._last_by_class[cls] = stored
        return changed

    def _class_head(self, cls: str) -> dict[str, Any] | None:
        """Display copy of the newest bird or bat event (fresh image, links)."""
        rec = self._last_by_class[cls]
        if rec is None:
            return None
        rec = dict(rec)
        img = self._image_urls.get(rec.get("sp_code")) or (
            self._bats.get(rec.get("species"), {}).get("image_url")
        )
        if img:
            rec["image_url"] = img
        return self._with_links([rec])[0]

    def _build_bats_today(self, overview: dict[str, Any]) -> list[dict[str, Any]]:
        """Today's bats by true detection count (BirdWeather's bat-filtered
        topSpecies), the bat counterpart of daily_top_species — without rarity,
        which is a bird measure. Behavior comes from each bat's latest event."""
        latest = {
            e.get("species"): e
            for e in reversed(self._event_buffer)
            if e.get("classification") == BAT
        }
        if (head := self._last_by_class[BAT]) is not None:
            latest[head.get("species")] = head
        result = []
        for rec in overview.get("bat_today_top") or []:
            ev = latest.get(rec["species"]) or {}
            result.append({
                **rec,
                "last_seen": self._last_seen.get(rec["species"]),
                **{k: ev.get(k) for k in ("behavior", "behavior_code", "behavior_confidence")},
            })
        return result

    def _is_bat(self, species: str) -> bool:
        """Whether a name in the first-seen log is a bat."""
        return species in self._bats

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
        picker in the options flow), sorted alphabetically. Bats only with bat
        support on."""
        return sorted(
            sp for sp in self._seen_species if self._bat_support or not self._is_bat(sp)
        )

    def _retry_after(self, err: Exception) -> float | None:
        """The API's Retry-After for a failed request, when it's worth honoring.

        Only a delay longer than the poll interval counts: Home Assistant uses
        retry_after as the next interval, so a shorter one would poll sooner.
        """
        seconds = getattr(err, "retry_after", None)
        interval = self.update_interval
        if seconds is None or (interval and seconds <= interval.total_seconds()):
            return None
        return seconds

    def _fire_event(self, trigger_type: str, record: dict[str, Any], **extra: Any) -> None:
        device = async_get_entry_device(
            self.hass, (DOMAIN, self.station_id), self.config_entry.entry_id
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
                "classification": record.get("classification") or BIRD,
                "species": record.get("species"),
                "scientific_name": record.get("scientific_name"),
                "sp_code": record.get("sp_code"),
                "image_url": record.get("image_url"),
                "audio_url": record.get("audio_url"),
                "confidence": record.get("confidence"),
                "confidence_band": record.get("confidence_band"),
                "last_seen": record.get("last_seen"),
                "rarity_score": record.get("rarity_score"),
                "yearly_rank": record.get("yearly_rank"),
                "behavior": record.get("behavior"),
                "behavior_code": record.get("behavior_code"),
                "behavior_confidence": record.get("behavior_confidence"),
                "count": record.get("count"),
                # Reference links, so automations (and the new-species
                # blueprint's buttons) can deep-link. Bats get only Wikipedia
                # and BirdWeather.
                **self._links_for(record.get("species", ""), record.get("sp_code", "")),
                **extra,
            },
        )

    # ------------------------------------------------------------------
    # Store helpers
    # ------------------------------------------------------------------

    def _store_for(self, suffix: str) -> Store:
        return Store(self.hass, _STORE_VERSION, f"{DOMAIN}.{self.station_id}.{suffix}")

    async def _load_stores(self) -> None:
        seen      = await self._store.async_load()
        last_seen = await self._last_seen_store.async_load()
        yearly    = await self._yearly_store.async_load()
        seven_day = await self._seven_day_store.async_load()
        events    = await self._events_store.async_load()
        by_class  = await self._by_class_store.async_load()
        if isinstance(by_class, dict):
            for cls in (BIRD, BAT):
                rec = by_class.get(cls)
                if isinstance(rec, dict) and rec.get("last_seen"):
                    self._last_by_class[cls] = rec

        self._seen_species   = seen      if isinstance(seen, dict)      else {}
        self._last_seen      = last_seen if isinstance(last_seen, dict) else {}
        self._baseline_items   = yearly    if isinstance(yearly, list)    else []
        self._baseline_available = isinstance(yearly, list)
        self._seven_day_data = seven_day if isinstance(seven_day, dict) else {}

        # The five cold per-species maps load from one species_meta store. On the
        # first load after upgrade it won't exist yet — assemble it from the old
        # per-map stores (migrate), then persist the consolidated copy.
        meta = await self._meta_store.async_load()
        migrated = False
        if not isinstance(meta, dict):
            meta = {}
            for key in _META_KEYS:
                data = await self._store_for(key).async_load()
                if isinstance(data, dict):
                    meta[key] = data
            migrated = bool(meta)

        def _d(key: str) -> dict:
            value = meta.get(key)
            return value if isinstance(value, dict) else {}

        self._sp_codes    = _d("sp_codes")
        self._sci_names   = _d("sci_names")
        self._image_urls  = _d("image_urls")
        self._image_attr  = _d("image_attr")
        self._links_cache = _d("links")
        self._bats        = _d("bats")

        if migrated:
            await self._save_meta()

        # Rehydrate the rolling event buffer so last_detection shows its last
        # value immediately after a restart (and survives an outage) instead of
        # "unknown" until the next live detection. Keep only well-formed records,
        # newest-first, capped — a corrupt/hand-edited store can't crash us.
        if isinstance(events, list):
            self._event_buffer = [
                e for e in events if isinstance(e, dict) and e.get("last_seen")
            ]
            self._event_buffer.sort(key=lambda e: e.get("last_seen") or "", reverse=True)
            del self._event_buffer[LAST_DETECTION_EVENT_LIMIT:]

        # One-time cleanup of the legacy per-map + .sticky stores now folded into
        # species_meta / the event buffer. async_remove no-ops if already gone.
        for legacy in _LEGACY_STORE_SUFFIXES:
            await self._store_for(legacy).async_remove()

        self._baseline_ranks = {
            item["species"]: item["rank"]
            for item in self._baseline_items
            if isinstance(item, dict) and item.get("species") and item.get("rank")
        }
        self._baseline_species_count = len(self._baseline_ranks)

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

    async def _import_history_statistics(self, today: date, earliest_iso: str) -> None:
        """Thin wrapper over statistics.async_import_history_statistics (keeps the
        recorder backfill — and its lazy recorder imports — out of this module)."""
        await async_import_history_statistics(
            self.hass,
            self._client,
            self.station_id,
            self.device_name,
            today,
            earliest_iso,
        )

    def _links_for(self, species: str, sp_code: str) -> dict[str, Any]:
        """Reference-link URLs for a record, surfaced by the integration so the
        cards just render them (no URL construction in the card). BirdWeather
        supplies authoritative eBird / Wikipedia / BirdWeather URLs (cached); All
        About Birds and Macaulay Library are templated (from the common name and
        the eBird code respectively). eBird falls back to a template if the
        upstream URL isn't cached yet. BirdWeather's species page has no template
        (it's a BirdWeather-only page), so it's only present once cached from the
        feed. Bats get only their Wikipedia and BirdWeather pages: eBird, All
        About Birds and Macaulay Library are bird references."""
        if bat := self._bats.get(species):
            return {
                "ebird_url": None,
                "wikipedia_url": bat.get("wikipedia_url"),
                "allaboutbirds_url": None,
                "macaulay_url": None,
                "birdweather_url": bat.get("birdweather_url"),
                "alpha": None,
                "alpha6": None,
            }
        cached = self._links_cache.get(sp_code) or {}
        return {
            "ebird_url": cached.get("ebird_url") or _ebird_url(sp_code),
            "wikipedia_url": cached.get("wikipedia_url"),
            "allaboutbirds_url": _allaboutbirds_url(species),
            "macaulay_url": _ml_url(sp_code),
            "birdweather_url": cached.get("birdweather_url"),
            # Alpha banding codes ride along on the same per-species cache so the
            # detail-view chip is consistent across every card list (incl. the
            # store-built and native-aggregate lists, not just the live feed).
            "alpha": cached.get("alpha"),
            "alpha6": cached.get("alpha6"),
        }

    def _with_links(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Stamp per-species metadata onto each record: reference-link URLs plus
        the diel `hourly` activity array (24 buckets) for the card's sparkline."""
        for r in records:
            r.update(self._links_for(r.get("species", ""), r.get("sp_code", "")))
            r["hourly"] = self._diel_by_species.get(r.get("species", ""))
        return records

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
        # A bird list: bats' first sightings fire new_species but aren't
        # listed here.
        sorted_items = sorted(
            ((sp, fs) for sp, fs in self._seen_species.items() if not self._is_bat(sp)),
            key=lambda kv: kv[1] or "",
            reverse=True,
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

    def _build_watched(self) -> list[dict[str, Any]]:
        """Watch-list species this station has detected, most-recently-heard
        first — powers the "Birds of interest" list card. Watched species the
        station has never recorded aren't listed (nothing to render); they're
        still covered by the watched_species device trigger when they arrive."""
        watched = self._watched_species()
        if not watched:
            return []
        denom = max(self._baseline_species_count, 1)
        result: list[dict[str, Any]] = []
        for species in self._seen_species:
            if species.casefold() not in watched:
                continue
            sp_code = self._sp_codes.get(species, "")
            rank = self._baseline_ranks.get(species, self._baseline_species_count)
            result.append({
                "species": species,
                "scientific_name": self._sci_names.get(species, ""),
                "sp_code": sp_code,
                "image_url": self._image_urls.get(sp_code),
                "last_seen": self._last_seen.get(species),
                "first_seen": self._seen_species.get(species),
                "rarity_score": round(rank / denom, 4),
                "yearly_rank": rank,
                **self._image_attribution(sp_code),
            })
        result.sort(key=lambda x: x.get("last_seen") or "", reverse=True)
        return result

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
        """Bird species ever recorded (the first-seen log also holds bats)."""
        return sum(1 for sp in self._seen_species if not self._is_bat(sp))
