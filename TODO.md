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
  busy stations. The headline 24h count/top-species/diversity now come from
  native `counts`/`topSpecies(period: 1 day)` (true totals — done), but the
  `daily_count` *list* still feeds the 7-day rarest rollup, notability scoring,
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
- Notification blueprints (`blueprints/automation/birdweather/`).
- README + docs (mirror haikubox docs/).
- GitHub remote + HACS metadata (`git init` + initial commit — done).
- Wordmark `logo.png` if a real BirdWeather wordmark asset turns up (currently
  icon-only; HA falls back to the icon).
