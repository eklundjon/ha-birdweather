# Sensors

All entities are grouped under a single device per BirdWeather station. Entity IDs are prefixed with your device name (e.g. `sensor.backyard_*`).

## The sensors

| Entity | State | Notable attributes |
|---|---|---|
| `sensor.recent_detections` | Species count in the current 1-hour window | `detections` (one per species, ranked by recency) |
| `sensor.last_detection` | Most recently heard species — the last detection regardless of age (persists across restarts/outages) | `detections` (one per event — rolling cache of the most recent 50, newest first; **survives outages**) |
| `sensor.daily_count` | True total detections over the trailing 24 h (BirdWeather's native count) | — (numeric total) |
| `sensor.daily_top_species` | Number of species in the trailing 24 h | `detections` (ranked by 24 h count) |
| `sensor.notable_species` | Most "notable" species in the last 24 h (tunable rarity/recency blend); **`unknown` when none observed** | `detections` (ranked by notability — drains with the 24 h window) |
| `sensor.new_species` | Most recently first-detected species | `detections` (lifetime history — most recent 50 first-seen), `lifetime_species_count` |
| `sensor.yearly_top_species` | Number of species in the rarity baseline | `detections` (ranked by baseline count) |
| `sensor.rarest_species` | Number of species, rolling 7 d | `detections` (ranked by rarity) |
| `sensor.lifetime_species` | Distinct species ever detected at this station | — (plain count; `MEASUREMENT` for long-term statistics) |
| `sensor.species_diversity` | Shannon diversity index (H′) over the last 24 h | `richness` (species count), `evenness` (Pielou H′/ln S, 0–1) |
| `sensor.activity_level` | Today's volume ÷ a typical day (1.0 ≈ normal, 2.0 ≈ twice as busy); **`unknown` until a baseline exists** | `detections_today`, `typical_daily_count` |
| `sensor.new_species_window` | How many species were first heard here in the last 30 days (discovery momentum) | — |
| `sensor.history_start` | **Diagnostic** — the station's earliest recorded detection (a timestamp) | — |
| `sensor.watched_species` | How many of your watch-list species the station has recorded | `detections` (your watched species, most-recently-heard first) |
| `sensor.peak_activity_hour` | The station's busiest hour of the day, over the trailing 7 days | `hourly_activity` (24-bucket curve), `peak_hour` |

### `sensor.lifetime_species`

A running count of every distinct species the station has ever detected — your "life list." It only rises (the lifetime `seen_species` log never shrinks) and carries a `MEASUREMENT` state class, so Home Assistant's long-term statistics chart it as a curve climbing over weeks and months. The same number is also exposed as the `lifetime_species_count` attribute on `new_species` for templates.

### Activity & discovery sensors

These summarise *how* active and varied the station is, computed from BirdWeather's **true** native per-period counts (not the detection-feed sample):

- **`species_diversity`** — the Shannon diversity index (H′) over the last 24 h: ~0 when one species dominates, higher when many species are heard evenly. `richness` (how many species) and `evenness` (Pielou's H′/ln S, 0–1) ride along as attributes.
- **`activity_level`** — today's detection total divided by a typical day (the mean over the trailing 30-day baseline): `1.0` is a normal day, `2.0` twice as busy, `0.5` half. `unknown` until there's a baseline. `detections_today` and `typical_daily_count` are exposed as attributes.
- **`new_species_window`** — how many species were first heard here in the last 30 days — a "discovery momentum" counter, high on a new install and settling toward 0 as the station learns the local regulars. (The window is tunable — see [advanced.md](advanced.md).)
- **`peak_activity_hour`** — the hour of the day the station is busiest, over the trailing 7 days, rendered as a time (e.g. `07:00`). The full 24-bucket `hourly_activity` curve is an attribute for chart cards.
- **`history_start`** *(diagnostic)* — a timestamp of the station's earliest recorded detection (BirdWeather's `earliestDetectionAt`), useful context for the activity/lifetime figures.

## Binary sensors

| Entity | Device class | On when |
|---|---|---|
| `binary_sensor.extended_silence` | `problem` | The station has logged **no** detections in the trailing 24 hours |

### `binary_sensor.extended_silence`

A station going a full day with zero detections almost always signals a real problem — offline, unpowered, or a failed microphone/connection — rather than a genuinely silent day. This `problem` binary sensor turns **on** in that case so you can alert on it directly. It's derived from the trailing-24 h `detections_24h` list. When a poll fails entirely the integration goes `unavailable` (see [api.md](api.md#failure-handling)) and this sensor goes unavailable too — "we don't know" rather than a false alarm. It lives in the device's Diagnostic section.

## PUC hardware sensors

For BirdWeather **PUC** stations the integration also creates onboard hardware sensors — but only the sub-suites your station actually reports (a BirdNET-Pi or other software station gets none). They're created from the first poll's data:

| Entity | Suite | Notes |
|---|---|---|
| `sensor.temperature` | environment | °C |
| `sensor.humidity` | environment | % |
| `sensor.barometric_pressure` | environment | hPa |
| `sensor.sound_pressure_level` | environment | dB |
| `sensor.voc` | environment | BME688 bVOCeq, ppm |
| `sensor.air_quality_index` | environment | BSEC IAQ (0–500) |
| `sensor.light_level` | light | broadband `clear` channel (luminance proxy) |
| `sensor.battery_voltage` | system | V *(diagnostic)* |
| `sensor.power_source` | system | e.g. USB-C *(diagnostic)* |
| `sensor.wifi_signal` | system | dBm *(diagnostic)* |
| `sensor.sd_card_free` | system | % free, with `free_gb`/`capacity_gb` attributes *(diagnostic)* |

## The `detections` contract

Every list-bearing sensor exposes its list under a single **`detections`** attribute. Each item is `{ species, scientific_name, sp_code, image_url, last_seen, rank, … }`, plus BirdWeather extras: `confidence`, `confidence_band` (low/medium/high), `audio_url` (when audio is enabled), `alpha`/`alpha6` banding codes, and the reference-link URLs (`ebird_url`, `wikipedia_url`, `allaboutbirds_url`, `macaulay_url`, `birdweather_url`). **`rank`** is a 1-based position assigned by *that sensor's own measure*:

| Sensor | `rank` 1 is | Basis |
|---|---|---|
| `recent_detections` | most recently heard | `last_seen` desc |
| `last_detection` | most recent event | `last_seen` desc |
| `notable_species` | most notable | `notability_score` desc (rarity ↔ recency blend) |
| `new_species` | most recently first-seen | `first_seen` desc |
| `daily_top_species` | most detected in 24 h | 24 h `count` desc |
| `yearly_top_species` | most detected in the baseline window | baseline `count` |
| `rarest_species` | rarest in the last 7 days | `rarity_score` desc |
| `watched_species` | most recently heard | `last_seen` desc |

Any of these can drive the `birdweather-bird-list-card`. `recent_detections` reads the 1-hour subset and `notable_species` the full 24-hour window; both come from the live detection feed and **drain when the station goes quiet/offline** — correct for an explicit window (`notable_species` goes `unknown`). `last_detection` is the exception: it reads a **persisted rolling cache** of the last 50 events, so it keeps showing the last detection through restarts and outages (#62).

### Per-species vs. per-event, live vs. persisted

The `detections` records on every sensor *except* `last_detection` are **per-species** — multiple events for the same species collapse into one record, with `count` = events-in-window and `last_seen` = the most recent event's timestamp.

`last_detection.detections` is **per-event**: one record per individual detection, from a persisted rolling cache of the 50 most recent events (newest first) that survives restarts and outages (#62). The field shape per record is otherwise the same, so the list card works pointed at either kind.

Most lists are **live** — recomputed every poll and going empty during quiet periods. Two **persist** instead:

- `new_species.detections` — the most recently first-seen species across the station's entire history, from the lifetime `seen_species` log; stays populated forever after the first species is seen.
- `last_detection.detections` — the 50 most recent individual events, held in a persisted rolling cache (`.storage/birdweather.<station_id>.recent_events`). Survives restarts and outages, so "the last detection" is always the last detection regardless of age (#62).

## Rarity scoring

`notable_species` and `rarest_species` score each species against the station's own rarity baseline — BirdWeather's `topSpecies` counts over a trailing window (default **1 month**, tunable; see [advanced.md](advanced.md)). A species absent from that window scores `1.0` (capped — tied with the rarest known species rather than overshooting); the most-detected species scores near `0`. So a Cooper's Hawk scores as more unusual at a station that rarely records raptors than at one that hears them daily.

## Notability tuning

`notable_species` blends rarity with recency:

> `notability_score = w · rarity_score + (1 − w) · recency_score`

`recency_score` is a linear decay over the trailing 24 hours — a detection right now scores 1.0; one at the 24-hour edge scores 0.0. The weight `w` is a slider in the integration's options (Settings → Devices & Services → BirdWeather → Configure):

- **100% rarity** — pure rarity; the list is dominated by the rarest species and changes slowly.
- **0% rarity** — pure recency; the top is whatever was heard most recently.
- **70% rarity** (default) — mostly rarity-driven, with enough recency that a fresh sighting can dethrone an old long-tail entry.

Changes take effect immediately — saving the options form reloads the entry, no waiting for the next poll.

## Confidence

BirdWeather reports a per-detection confidence (0–1). The integration derives a low/medium/high `confidence_band` and surfaces it on every record (the cards show a colored chip). Two independent options gate on confidence (see [advanced.md](advanced.md) is not where these live — they're top-level options): a **feed filter** hides low-confidence "maybe" detections from the recent/last/notable/new sensors and cards, and an **alert filter** gates the device triggers. The 24-hour total and diversity counts come from BirdWeather's own aggregates and are not affected by the feed filter.

## Persistent state

`last_detection` never clears: its rolling event cache is persisted and rehydrated on startup, so it shows the last detection through restarts and outages (#62). `notable_species` is deliberately **not** persisted — it drains to `unknown` (with the bird-off icon) after 24 h with nothing observed. `new_species` persists via the lifetime first-seen log.

Data written to `.storage/` (six files per station; see [architecture.md](architecture.md)):

| Store file | Contents |
|---|---|
| `birdweather.<station_id>.seen_species` | Lifetime first-detection log |
| `birdweather.<station_id>.last_seen` | Species → most recent detection timestamp |
| `birdweather.<station_id>.yearly` | The rarity baseline (`topSpecies` ranks) |
| `birdweather.<station_id>.seven_day` | Per-day rarity records for the 7-day `rarest_species` window |
| `birdweather.<station_id>.recent_events` | Rolling cache of the 50 most recent events (backs `last_detection`) |
| `birdweather.<station_id>.species_meta` | Per-species lookups (codes, scientific names, image URLs, photo attribution, reference links) |
