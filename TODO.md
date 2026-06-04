# ha-birdweather — follow-ups

Backlog for the BirdWeather integration (PoC stage). Convert to GitHub issues
when the repo is pushed.

## Image attribution / licensing  ✅ done

Photo credit/license is now fetched (`imageCredit`/`imageLicense`/
`imageLicenseUrl`), sanitised from BirdWeather's HTML credit to plain text + a
URL in `client.py`, cached per species, threaded onto every record, and shown
as a caption on the bird card (overlay) and the list card (detail view).
Default on, with a "Show photo credit" card toggle (`show_attribution`).

Possible follow-ups:
- Some images have no credit/license from the API (caption is omitted) — could
  fall back to a generic "Photo: BirdWeather" line.
- `imageCredit` is occasionally a bare URL rather than a name; left as-is.

## Real-time detections via GraphQL subscription (push, not polling)

BirdWeather has a first-party **push API** the cloud-polled, audio-only Haikubox
lacks — a strong reason to migrate hardware Haikubox → PUC. It's a GraphQL
**subscription** `newDetection` over WebSocket (their site uses Apollo's `split`
link → WS for subscriptions; *not* Action Cable — `/cable` 404s).

- Operation: `subscription { newDetection(<filters>) { detection { … } } }`
  → `NewDetectionPayload { detection: Detection! }` (the full `Detection` we
  already parse from the REST/GraphQL feed).
- Server-side filters (so it's not a firehose): `stationIds`, `speciesIds`,
  `classifications`, `confidence/score/probabilityGte/Lte`, `timeOfDayGte/Lte`,
  `countries`/`continents`, `recordingModes`, `overrideStationFilters`.
- Consume with `gql` (`WebsocketsTransport`) or `websockets` speaking the
  `graphql-ws` protocol: one **outbound** WS (NAT-friendly, no ingress),
  subscribe with `stationIds: [<id>]` + a min-confidence filter; on each event
  update `last_detection` and fire `new_species` / `unusual_visitor` in real
  time. Keep the 10-min poll for the aggregate sensors (counts / baseline /
  activity) and as a reconnect fallback.

Prerequisite — confirm the transport (the API docs list the *operation* but not
the endpoint/protocol/auth):
- DevTools → Network → WS on app.birdweather.com (its live map runs this
  subscription) reveals the `wss://` URL, the `Sec-WebSocket-Protocol`
  (`graphql-transport-ws` vs legacy `subscriptions-transport-ws`), the
  `connection_init` payload (any token), and a sample `newDetection` message.
- Or ask support@birdweather.com.

For the real-time path this largely supersedes the "switch the recent feed to a
time-bounded form" item under Data-window correctness.

## BirdWeather-only feature roadmap

Features the BirdWeather API enables that Haikubox structurally can't. Listed in
the agreed priority order. **Only tier 3 (environment/device sensors) needs PUC
hardware**; everything else works on *any* BirdWeather station (including a
BirdNET-Pi registered to BirdWeather). The real-time push API (above) is the
companion to these. Bonus already realised: BirdWeather's `detections` feed is
real + paginated (not a ≤5-per-species sample), so accurate volume / diversity /
event timelines just work.

### 1. Species-centric tracking + canonical metadata
Every record already carries `scientificName`, `ebirdCode`, `ebirdUrl`,
`wikipediaUrl`, `imageUrl` (+ credit/license); the API also filters by
`speciesIds` / `classifications`. Haikubox `/daily-count` is common-name-only and
has no species-scoped queries (it forced a bundled 768 KB eBird map for
codes/sci-names/images).
- A **"watch species" option** → a filtered `newDetection` subscription / alert
  that fires only for chosen species (e.g. Painted Bunting).
- Cards: link out via the canonical `ebirdUrl` / `wikipediaUrl` when present
  (we currently template eBird/AllAboutBirds URLs from tokens).
- Drop any reliance on a bundled taxonomy — BirdWeather supplies codes,
  scientific names, images and links directly.
- A **"Birds of interest" watchlist card** — a list filtered to chosen species
  with last-heard (the watchlist as a dashboard element, not just an alert);
  community-validated.

### 2. Detection confidence / certainty
`Detection` exposes `confidence`, `score`, `certainty`, `probability`;
`topSpecies` has `averageProbability`; the station reports its own
`minConfidence`; the subscription filters on `confidenceGte`. Haikubox exposes
nothing usable here. (The coordinator already threads `confidence` onto records.)
- A **min-confidence filter** option (suppress "maybe" detections).
- Confidence / certainty **display + badge** on cards.
- **Confidence-gated alerts** — pairs with the push subscription's
  `confidenceGte` to cut false-positive pings on rare birds.

### 3. Environment + device-health sensors (PUC hardware)
`Station.sensors` exposes a full onboard suite — the one tier that genuinely
needs a PUC; turns the bird box into a real outdoor environment + air-quality
station and gives true device health (vs Haikubox's audio-only "is it silent?").
- `sensors.environment`: `temperature` (°C), `humidity` (%), `barometricPressure`
  (hPa), `soundPressureLevel` (dB), `voc`, `eco2`, `timestamp`. Map to HA
  device classes (temperature/humidity/pressure/sound_pressure).
- `sensors.light`: spectral (AS7341-style) — `clear` (broadband), `f1`–`f8`,
  `nir`. No lux field; expose `clear` as a luminance proxy (derive illuminance
  later if wanted).
- `sensors.system`: `batteryVoltage` (V), `powerSource`, `wifiRssi` (dBm),
  SD capacity, upload progress — diagnostic entities (entity_category diagnostic).
- `weather` / `airPollution`: OpenWeather-sourced (temp, humidity, wind, AQI,
  PM2.5, …) but **only when the owner enables `openWeather`** (else null).

Implementation notes:
- Extend the coordinator to fetch `sensors { environment{…} light{…} system{…} }`
  (one query, alongside detections) and stash the latest readings.
- Create sensor entities **conditionally** — a BirdNET-Pi station registered on
  BirdWeather has no hardware sensors (all null); only add entities the station
  actually reports.
- `eco2` returned a clearly bogus value (−19919) on a test unit — validate /
  clamp before surfacing.
- Sensor `timestamp` is independent of detection timestamps (last reading).

### 4. Detection audio ("play the call")
Every `Detection` carries `soundscape{url}` (the recording), already threaded as
`audio_url`. Haikubox drops its `wav` entirely (open issue #41 is a *request*).
- "Play the call" affordance on the bird card from `audio_url`.
- A `media_source` of recent detections; announce a notable/new bird's call on a
  speaker; **audio verification** of a rare ID by ear before trusting it.
- Stretch: **generate a shareable clip** (MP4) from the detection audio with
  overlaid metadata (species, confidence, time) — the BirdNET-Go community does
  this with ffmpeg over their audio clips.

### 5. Time-of-day / activity patterns
`timeOfDayDetectionCounts` + `timeOfDayGte/Lte` filters. Haikubox has only
whole-day totals.
- A **diel activity heatmap** / "dawn chorus" card; "most active hour" per
  species.
- A compact **per-species hourly sparkline for *today*** (Unicode ▁▂▃▅▇ bars
  across the hours), straight from `timeOfDayDetectionCounts` — a
  community-favourite, very information-dense card.

### 6. Regional / cross-station context
`stations(query, ne, sw)` discovery (already used in onboarding) +
`countries`/`continents` filters on detections and subscriptions. Haikubox is
single-box only.
- **"Rare here but common nearby"** — a novel rarity signal (your station's
  baseline vs the neighbourhood's).
- A **regional rare-bird feed**; diversity/activity **percentile vs nearby
  stations**.
- Heavier: needs extra queries against nearby station IDs.

### 7. History & phenology
`InputDuration` accepts arbitrary `from`/`to` ranges over true per-day counts;
`earliestDetectionAt` gives history start. Haikubox is one-day-at-a-time,
common-name-only, with a painful backfill.
- **Seasonality / migration charts**, **first-arrival dates** per species,
  **year-over-year** comparisons, long-term trend sensors / a statistics view.
- **Trends without Grafana:** give the numeric sensors a `state_class`
  (measurement/total) so HA's built-in long-term Statistics graphs them
  natively — the community typically bolts on Grafana; we can skip that for the
  common case.
- Relates to the Data-window-correctness items below.

## Data-window correctness

- `DETECTION_FETCH_LIMIT` (300 recent events) can fail to span a full 24h on
  busy stations. The headline 24h count/top-species/diversity now come from
  native `counts`/`topSpecies(period: 1 day)` (true totals — done), but the
  `detections_24h` *list* still feeds the 7-day rarest rollup, notability scoring,
  and the recent/last-detection records from the paginated feed. Switch that
  feed to a time-bounded form (`from`/`period` + cursor pagination) for a true
  24h event list.
- Day boundaries are currently UTC (inherited from haikubox). For a
  fixed-location station, keying the 7-day store / daily windows to the
  station's timezone is arguably more correct.
- Rarity baseline period defaults to 1 month (`RARITY_PERIOD_MONTHS`); many
  species fall outside it and cap at rarity 1.0. Consider a longer window or
  surfacing the period as an option.

## Packaging / parity with haikubox

- `diagnostics.py` (redacted state dump).
- Notification blueprints (`blueprints/automation/birdweather/`) — bake in the
  community's hard-won UX: a **cooldown timer** (avoid spam), **per-person /
  per-channel targets with distinct conditions**, **custom sounds**, and the
  **absence gap in the rare-return message** (the `unusual_visitor` event
  already carries `days_absent`). Add a **"quiet period" alert** (short silence)
  that **suppresses at night and in winter** — a softer companion to the 24h
  `extended_silence`.
- README + docs (mirror haikubox docs/).
- GitHub remote + HACS metadata (`git init` + initial commit — done).
- Wordmark `logo.png` if a real BirdWeather wordmark asset turns up (currently
  icon-only; HA falls back to the icon).

## Community patterns & cross-integration (survey notes, 2026-06-04)

Surveyed BirdNET-Pi / BirdNET-Go / BirdWeather HA setups. They validate the
roadmap above (photo+name+time cards, latest-detections feed, first-time +
rare-return alerts, eBird links, audio playback, confidence display, and
recorder-excluded list attributes). The concrete extras are folded into the
tiers above. Still open:

- **Feeder-camera correlation** (stretch, novel): pair an audio detection with a
  Frigate / WhosAtMyFeeder camera snapshot at detection time — "heard *and* saw
  it." A cross-integration nobody combines yet.
- **Restart rehydration for the push path:** whatever real-time transport we add
  must restore last-detection on restart (the community relies on the MQTT
  `retain` flag; we already persist sticky state — keep that invariant).

Sources: kyleniewiada BirdNET-Go writeup; rhett.cc BirdNET-Pi→HA MQTT guide; HA
community BirdWeather-PUC and BirdNET-Go detection threads; WhosAtMyFeeder
(Frigate camera ID).

## Known limitations (upstream — not client-fixable)

- **Tightly-cropped species photos.** BirdWeather serves one **400×400 square**
  crop per species (a contributor/Wikimedia image), and some are cropped tight
  enough to clip the bird. The card uses `object-fit: contain` (+ blur-fill), so
  it shows the *whole* file and never crops further — but it can't recover pixels
  BirdWeather already cut, and `standard`/`thumbnail` share the same crop. Not
  fixable from HA; documented in the README troubleshooting section. Sourcing the
  full image elsewhere (Wikimedia/eBird via `wikipediaUrl`/`ebirdUrl`) is the only
  workaround and isn't worth the licensing/complexity for occasional bad crops.
  - Running list of clipped species worth reporting upstream to BirdWeather:
    - **Painted Bunting** (`Passerina ciris`, species 2376) — beak clipped at the
      right edge (image credit: Doug Janson, CC BY-SA 3.0).
