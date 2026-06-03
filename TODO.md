# ha-birdweather — follow-ups

Backlog for the BirdWeather integration (PoC stage). Convert to GitHub issues
when the repo is pushed.

## Image attribution / licensing  ⚠️ before any public release

We display BirdWeather `Species.imageUrl` photos **without their credit/license**.
Those are licensed images (often Macaulay Library / contributor photos), so
attribution is likely required.

- The GraphQL `Species` type also exposes `imageCredit`, `imageLicense`,
  `imageLicenseUrl`. Add them to the species sub-selection in
  `client.py` (`_DETECTIONS_QUERY`, and the topSpecies/station queries as
  relevant).
- Thread them through `get_raw_detections()` → `_normalise_detections()` onto
  each record (e.g. `image_credit`, `image_license`, `image_license_url`).
- Surface them: a small caption/attribution on the bird card (and/or expose as
  state attributes). At minimum, credit + license text near the photo.
- Decide policy: show attribution always, or make it a card toggle.

## Surface BirdWeather-only data the pipeline already carries

The coordinator threads `audio_url` (soundscape FLAC) and `confidence` onto
records, but the (haikubox-derived) cards don't render them yet.

- "Play the call" affordance on the bird card from `audio_url`.
- Optional confidence display / a min-confidence filter option (the station
  also reports its own `minConfidence`).

## Environmental / system sensors (PUC hardware)

The API exposes a full onboard sensor suite under `Station.sensors` that we
don't surface today — a BirdWeather PUC could back a richer HA device than the
audio-only Haikubox.

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

## Data-window correctness

- `DETECTION_FETCH_LIMIT` (300 recent events) can fail to span a full 24h on
  busy stations — switch the detections query to a time-bounded form
  (`from`/`period` args) with cursor pagination for a true 24h window.
- Day boundaries are currently UTC (inherited from haikubox). For a
  fixed-location station, keying the 7-day store / daily windows to the
  station's timezone is arguably more correct.
- Rarity baseline period defaults to 1 month (`RARITY_PERIOD_MONTHS`); many
  species fall outside it and cap at rarity 1.0. Consider a longer window or
  surfacing the period as an option.

## Packaging / parity with haikubox

- `diagnostics.py` (redacted state dump).
- Notification blueprints (`blueprints/automation/birdweather/`).
- README + docs (mirror haikubox docs/).
- `git init` + initial commit + GitHub remote; then HACS metadata.
- Wordmark `logo.png` if a real BirdWeather wordmark asset turns up (currently
  icon-only; HA falls back to the icon).
