from __future__ import annotations

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

from .client import BirdWeatherClient, BirdWeatherError
from .const import (
    ACTIVITY_BASELINE_DAYS,
    CONF_ABSENCE_DAYS,
    CONF_ALERT_MIN_CONFIDENCE,
    CONF_AUDIO_ENABLED,
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

_STORE_VERSION = 1

# Per-station .storage suffixes — the full set, removed when the entry is removed
# (see async_remove_stores). Keep in sync with the Store(...) creation in __init__.
_STORE_SUFFIXES = (
    "seen_species",
    "sp_codes",
    "sci_names",
    "last_seen",
    "image_urls",
    "image_attr",
    "links",
    "yearly",
    "seven_day",
    "recent_events",
)

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

        # Persistent stores
        self._store           = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.seen_species")
        self._sp_codes_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.sp_codes")
        self._sci_names_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.sci_names")
        self._last_seen_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.last_seen")
        self._images_store     = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.image_urls")
        self._image_attr_store = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.image_attr")
        self._links_store      = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.links")
        self._yearly_store     = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.yearly")
        self._seven_day_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.seven_day")
        self._events_store     = Store(hass, _STORE_VERSION, f"{DOMAIN}.{station_id}.recent_events")

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
        self._baseline_items: list[dict[str, Any]] = []
        self._seven_day_data: dict[str, list] = {}

        # unusual_visitor edge detection (None until first poll baselines).
        self._prev_recent_species: set[str] | None = None

    # ------------------------------------------------------------------
    # DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_setup(self) -> None:
        """One-time setup before the first refresh: rehydrate persisted stores."""
        await self._load_stores()

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
            img = self._image_urls.get(e.get("sp_code"))
            if img:
                e["image_url"] = img
            if not audio_enabled:
                e["audio_url"] = None
        _apply_rarity_scores(view, self._baseline_ranks, self._baseline_species_count)
        return view

    @staticmethod
    async def async_remove_stores(hass: HomeAssistant, station_id: str) -> None:
        """Delete this station's persistent .storage files.

        Called from async_remove_entry when the integration entry is removed.
        Store.async_remove() no-ops if a file is already gone."""
        for suffix in _STORE_SUFFIXES:
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
                await self._yearly_store.async_save(self._baseline_items)
            except (aiohttp.ClientError, BirdWeatherError) as err:
                _LOGGER.warning("Could not fetch rarity baseline: %s", err)

        if not self._baseline_ranks:
            raise UpdateFailed(
                "Rarity baseline not yet available — topSpecies fetch failed on "
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
                self.station_id, first=DETECTION_FETCH_LIMIT
            )
        except (aiohttp.ClientError, BirdWeatherError) as err:
            raise UpdateFailed(f"Error communicating with BirdWeather API: {err}") from err

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

        now = datetime.now(UTC)
        # The fetch returns the most-recent N events regardless of age; carve
        # the trailing 24h (and the 1h subset) out of it client-side. Busy
        # stations may exhaust the limit inside 24h — see DETECTION_FETCH_LIMIT.
        recent_hours = self.config_entry.options.get(
            CONF_RECENT_WINDOW_HOURS, RECENT_WINDOW_HOURS
        )
        daily_raw = {"detections": _filter_by_dt(raw_all, now - timedelta(hours=DAILY_WINDOW_HOURS))}
        recent_raw = {"detections": _filter_by_dt(daily_raw, now - timedelta(hours=recent_hours))}

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
        links_dirty = False
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
                links_dirty = True
        if links_dirty:
            await self._links_store.async_save(self._links_cache)

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
        poll_events = _build_recent_events(
            daily_raw,
            self._baseline_ranks,
            self._baseline_species_count,
            self._image_urls.get,
            LAST_DETECTION_EVENT_LIMIT,
            audio_enabled,
        )
        if self._merge_event_buffer(poll_events):
            await self._events_store.async_save(self._event_buffer)

        self._fire_detection_events(detections, newly_seen, prior_last_seen)

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
        attr_dirty = False
        for rec in today_top:
            rec["last_seen"] = self._last_seen.get(rec["species"])
            if self._cache_image_attr(rec.get("sp_code", ""), rec):
                attr_dirty = True
        if attr_dirty:
            await self._image_attr_store.async_save(self._image_attr)
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
                overview.get("lifetime_species") or len(self._seen_species)
            ),
            "yearly_top_species": self._with_links(self._build_baseline_top()),
            "rarest_species": _ranked(self._with_links(seven_day_rare)),
            "watched_species": _ranked(self._with_links(self._build_watched())),
            "sensors": sensors,
            # Diel activity (trailing 7-day, station-wide): the hourly curve for a
            # chart card + the peak hour for the "Peak activity hour" sensor.
            "hourly_activity": self._diel_station or None,
            "peak_activity_hour": _peak_hour(self._diel_station),
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
                    lifetime_species_count=len(self._seen_species),
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
                "confidence_band": record.get("confidence_band"),
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
        links     = await self._links_store.async_load()
        yearly    = await self._yearly_store.async_load()
        seven_day = await self._seven_day_store.async_load()
        events    = await self._events_store.async_load()

        self._seen_species   = seen      if isinstance(seen, dict)      else {}
        self._sp_codes       = sp_codes  if isinstance(sp_codes, dict)  else {}
        self._sci_names      = sci_names if isinstance(sci_names, dict) else {}
        self._last_seen      = last_seen if isinstance(last_seen, dict) else {}
        self._image_urls     = images    if isinstance(images, dict)    else {}
        self._image_attr     = image_attr if isinstance(image_attr, dict) else {}
        self._links_cache    = links     if isinstance(links, dict)     else {}
        self._baseline_items   = yearly    if isinstance(yearly, list)    else []
        self._seven_day_data = seven_day if isinstance(seven_day, dict) else {}

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

        # One-time cleanup of the legacy .sticky store (the rolling event buffer +
        # live notable replace it — #62). async_remove no-ops if already gone.
        await Store(
            self.hass, _STORE_VERSION, f"{DOMAIN}.{self.station_id}.sticky"
        ).async_remove()

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
        feed."""
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
        return len(self._seen_species)
