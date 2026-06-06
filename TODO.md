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

### 1. Species-centric tracking + canonical metadata  ✅ done
Every record carries `scientificName`, `ebirdCode`, `ebirdUrl`, `wikipediaUrl`,
`imageUrl` (+ credit/license); the `Species` type adds `birdweatherUrl`, `mlUrl`,
`wikipediaSummary`, `alpha`/`alpha6`, `color`. Haikubox `/daily-count` is
common-name-only with no species-scoped queries (it forced a bundled 768 KB
eBird map for codes/sci-names/images) — the structural contrast.
- ✅ **Watch-species option + alert** (device trigger) — shipped earlier, ported
  to Haikubox. *Portable.*
- ✅ **"Birds of interest" watchlist card** (Watched species sensor + list card)
  — shipped earlier. *Portable.*
- ✅ **Canonical reference links** — eBird / All About Birds (earlier) plus
  **Macaulay Library** (templated from `sp_code` → `…/catalog?taxonCode=`,
  *portable to HB*) and **BirdWeather** (native `birdweatherUrl`, *BW-only*).
  Wikipedia is no longer a pill — it's reached by tapping the description blurb.
- ✅ **Species description** — surfaced as a tappable blurb in the list card's
  expanded detail, **fetched on demand by the card from Wikipedia's REST API**
  (CORS-enabled) when a row opens, cached per session; tapping it opens the full
  article (with a persistent "Read more on Wikipedia ›" cue for discoverability).
  Integration stays lean (static data, no polling/state bloat). *Portable* — both
  cards have a `wikipedia_url` (native on BW, templated from sci-name on HB).
- ✅ **Alpha banding codes** (`alpha`/`alpha6`) threaded onto records as
  attributes; shown as a chip in the detail view. *BW-only → HB API ask.*
- BirdWeather never needed a bundled taxonomy — it supplies all of the above
  natively. Haikubox's 768 KB eBird bundle is the workaround; the API ask is to
  expose per-detection species metadata (sp_code, sci-name, image, links, alpha)
  in `/detections` & `/daily-count`.

Follow-up (separate PR): port the *portable* pieces to Haikubox — Macaulay
Library link (template from sp_code) and the on-demand Wikipedia description blurb.

### 2. Detection confidence / certainty  ✅ done
`Detection` exposes `confidence`, `score`, `certainty`, `probability`;
`topSpecies` has `averageProbability`; the station reports its own
`minConfidence`. Haikubox exposes **nothing** usable here — `/detections` items
are `{sn, wav, dt, cn, spCode, offset}`, no confidence; its app's low/med/high
bands are BirdNET-internal and not in the public API. So this tier is
BirdWeather-only.
- ✅ **Feed min-confidence** option — drops low-confidence "maybe" events from
  the feed-derived sensors (recent/last/24h/notable/new/watched/silence) before
  windowing. Native count/diversity/activity aggregates are server-side and
  unaffected (they reflect the station's own `minConfidence`).
- ✅ **Alert min-confidence** option — independent gate on the new/unusual/
  watched device triggers, so you can see maybes but only be pinged on confident
  hits. (`confidence_band` is also threaded into the trigger payload.)
- ✅ **Confidence badge** on cards — a low/medium/high band *derived from the
  numeric confidence* (BirdWeather's own `certainty` is ~99% "almost_certain"
  across 0.36–0.98, useless as a label). Cutoffs in `const` (low <55 / med
  55–80 / high ≥80), tuned to the real distribution; both cards have a
  `show_confidence` toggle (default on).
- Future (needs the push subscription): server-side `confidenceGte` on the
  live feed so gating happens upstream instead of client-side. See the
  subscription section above.

### 3. Environment + device-health sensors (PUC hardware)  ✅ done
`Station.sensors` exposes a full onboard suite — the one tier that genuinely
needs a PUC; turns the bird box into a real outdoor environment + air-quality
station and gives true device health (vs Haikubox's audio-only "is it silent?").
Shipped (conditional on the station reporting each sub-suite — a BirdNET-Pi gets
none): a description-driven `BirdWeatherHardwareSensor`, gated on the first
refresh's `data["sensors"]`.
The gas block is a **Bosch BME688 via the BSEC library**: `voc` = bVOCeq (ppm),
`aqi` = BSEC IAQ index (0–500), `eco2` = a CO2-equivalent *estimate* (no real
CO2 cell).
- ✅ **environment**: `temperature`, `humidity`, `barometricPressure`,
  `soundPressureLevel`, `voc`, `aqi` — mapped to HA device classes (temperature /
  humidity / atmospheric_pressure / sound_pressure / volatile_organic_compounds_parts
  (ppm) / aqi).
- ✅ **light**: broadband `clear` channel surfaced as "Light level" (a luminance
  proxy — not lux, so no illuminance device class). Spectral `f1`–`f8` / `nir`
  deferred (niche).
- ✅ **system** (diagnostic): `batteryVoltage` (V), `powerSource`, `wifiRssi`
  (dBm), SD free % (+ free/total GB attrs).
- **eco2 skipped** — fleet survey (197 public PUCs): 38% read below the ~420 ppm
  atmospheric floor (some negative, e.g. −28215 on 20184; only ~47% plausible).
  It's an unreliable derived estimate, not just a per-unit fluke — clamping can't
  fix it. Revisit only if BirdWeather's firmware fixes the BSEC eCO2 output.
- Each entity exposes the reading's own `timestamp` as `last_reading`.

Deferred to a later PR:
- `weather` / `airPollution`: OpenWeather-sourced (temp, humidity, wind, AQI,
  PM2.5, …) but **only when the owner enables `openWeather`** (null on station
  20184, so untestable now) — and largely redundant with HA's own weather.
- Spectral light channels, accel/mag, GPS location.

### 4. Detection audio ("play the call")
Every `Detection` carries `soundscape{url}` (the recording), already threaded as
`audio_url`. Haikubox drops its `wav` entirely (open issue #41 is a *request*).
- "Play the call" affordance on the bird card from `audio_url`.
- A `media_source` of recent detections; announce a notable/new bird's call on a
  speaker; **audio verification** of a rare ID by ear before trusting it.
- Stretch: **generate a shareable clip** (MP4) from the detection audio with
  overlaid metadata (species, confidence, time) — the BirdNET-Go community does
  this with ffmpeg over their audio clips.

### 5. Time-of-day / activity patterns  ✅ done
`timeOfDayDetectionCounts` returns one BinnedSpeciesCount per species with sparse
half-hourly bins; the client folds these to 24 hourly buckets and sums a
station-wide curve. Fetched once per calendar day over a trailing 7-day window
(`DIEL_WINDOW_DAYS`) — a "typical rhythm" rather than today-only (sparse).
- ✅ **Peak activity hour** sensor (station-wide "dawn chorus" peak): state =
  busiest hour `HH:00`; attributes `hourly_activity` (24-bucket curve, for a
  chart card) + `peak_hour` (int).
- ✅ **Per-species hourly sparkline** in the list-card detail (Unicode ▁▂▃▅▇,
  one block/hour, scaled to the species' own max) + "most active ~HH:00", behind
  a `show_activity` toggle. The `hourly` array is stamped onto records via
  `_with_links`, so it's consistent across every card list.
- Follow-up (not built): a dedicated **diel heatmap card** (the `hourly_activity`
  attribute already feeds any chart card, e.g. apexcharts, in the meantime). For
  a today-vs-typical view, prefer a **`sparkline_window` config option
  (1-day | 7-day)** over adding a *second* sparkline — the detail card is already
  content-dense (see Cards / UI). 1-day would need a per-poll fetch (today
  changes through the day) vs the once-daily 7-day fetch.

### 6. Regional / cross-station context
`stations(query, ne, sw)` discovery (already used in onboarding) +
`countries`/`continents` filters on detections and subscriptions. Haikubox is
single-box only.
- **"Rare here but common nearby"** — a novel rarity signal (your station's
  baseline vs the neighbourhood's).
- A **regional rare-bird feed**; diversity/activity **percentile vs nearby
  stations**.
- Heavier: needs extra queries against nearby station IDs.

### 7. History & phenology  🟡 partial (A shipped)
`InputDuration` accepts arbitrary `from`/`to` ranges over true per-day counts
(`dailyDetectionCounts` → `{date, total, counts}`); `earliestDetectionAt` gives
history start. Haikubox is one-day-at-a-time, common-name-only, painful backfill.
- ✅ **A. Historical statistics backfill ("trends without Grafana, done right").**
  `_import_history_statistics` backfills HA long-term statistics from the first
  recorded day to today, once/calendar-day (idempotent), via
  `async_add_external_statistics`: `birdweather:station_<id>_daily_detections`
  (cumulative `sum` → per day/week/month bars) and `..._daily_species` (daily
  `mean` richness). Spiked + verified end-to-end against a real recorder. The
  `state_class` baseline (graphs going *forward*) was already in place; this adds
  the *past*.
  - Follow-up: full re-import each day is fine at typical lengths; a busy
    multi-year station could import incrementally via `get_last_statistics`.
    Also consider clearing the external stats on integration removal (currently
    orphaned).
- **B. First-arrival dates / phenology** (not built): per-species first
  detection-of-the-year ("spring arrivals") from per-species `dailyDetectionCounts`.
  Richer with multi-year history.
- **C. Year-over-year** (not built): needs ≥1 year of history (`dayOfYear`
  alignment). Test station 20184 only goes back to 2025-12-25.
- **D. Seasonality curve** (not built): per-species detections-by-week-of-year —
  the seasonal sibling of the diel sparkline. Adds to the (already dense) detail
  card → prefer its own card / a window toggle (see Cards / UI).

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

## Reference links

- **Template reference links missing from the upstream cache.** `_links_for`
  surfaces eBird + Wikipedia from the persisted `.links` cache (populated from
  the detection feed). eBird already falls back to a `sp_code` template when a
  species isn't cached; **Wikipedia does not**, so watch-list / baseline species
  not heard this session (e.g. right after a restart) show no Wikipedia link
  until re-heard. Add a scientific-name fallback
  (`https://en.wikipedia.org/wiki/<Genus_species>` — verified ~100% reliable via
  Wikipedia's binomial redirects; haikubox already templates Wikipedia this way),
  preferring the authoritative upstream URL when cached. Pass `scientific_name`
  into `_links_for`. Minor.

## Cards / UI

- **Detail-view content density.** The list card's expanded detail has grown a
  lot — eBird / All About Birds / Macaulay / BirdWeather links, confidence band,
  alpha code, Wikipedia description, activity sparkline, photo attribution — each
  behind its own toggle. Consider curating/grouping (e.g. a compact vs. full
  detail mode, or collapsing secondary metadata) rather than adding more rows.
  New per-species datapoints should reuse an existing affordance (e.g. a window
  toggle on the sparkline) over a new line.
- **Revisit bird-card responsiveness holistically.** The portrait layout
  reserves a *fixed* text strip below the photo (`clamp()` heights in the
  `.img-wrap` formulas) sized for a worst-case line count. Adding the confidence
  line (Tier 2) overflowed the old reserve and clipped the species name; fixed
  for now by enlarging the reserves (base `clamp(104px, 34cqh, 200px)`,
  short-portrait `clamp(86px, 30cqh, 160px)`) and hiding the band on very short
  wide cards. This works but is brittle — every new text line re-opens the math.
  Consider switching to a content-sized text block with the photo filling the
  remainder (`.body { flex: 0 0 auto }`, image `flex: 1 1 auto`), so text can
  never overflow into the photo regardless of line count. The blocker is the
  portrait-priority width formulas that derive the photo width from its
  (currently explicit) height; a flex-shrunk height breaks them, so it needs a
  rethink of those queries. Bigger change — deferred out of the Tier 2 PR.

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
