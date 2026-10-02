# Sensors

Each BirdWeather station gets one device in Home Assistant, and all of its entities live under that device. Entity IDs start with the device name, for example `sensor.backyard_last_detection`.

## The sensors

| Entity | State | Useful attributes |
|---|---|---|
| `sensor.recent_detections` | Number of species heard in the last hour | `detections`, one per species, most recent first |
| `sensor.last_detection` | The most recent bird heard, however long ago (or bat, with [bat support](bats.md) on). Keeps its value through restarts and outages. | `detections`, the last 50 individual detections, newest first |
| `sensor.daily_count` | Total detections in the last 24 hours, from BirdWeather's own count | None |
| `sensor.daily_top_species` | Number of species heard in the last 24 hours | `detections` ranked by 24-hour count |
| `sensor.notable_species` | The most notable bird of the last 24 hours. `unknown` if nothing was heard. | `detections` ranked by notability |
| `sensor.new_species` | The most recent species heard for the first time at the station | `detections`, the last 50 first-time species; `lifetime_species_count` |
| `sensor.yearly_top_species` | Number of species in the rarity baseline | `detections` ranked by baseline count |
| `sensor.rarest_species` | Number of species heard in the last 7 days | `detections` ranked by rarity |
| `sensor.lifetime_species` | Number of different species the station has ever heard | None |
| `sensor.species_diversity` | Shannon diversity index (H′) for the last 24 hours | `richness`, `evenness` |
| `sensor.activity_level` | Today's detections compared to a typical day (1.0 is normal, 2.0 is twice as busy). `unknown` until there's a baseline. | `detections_today`, `typical_daily_count` |
| `sensor.new_species_window` | Number of species heard for the first time in the last 30 days | None |
| `sensor.history_start` | Diagnostic. The station's earliest recorded detection. | None |
| `sensor.watched_species` | How many of your watched species the station has heard | `detections`, your watched species, most recently heard first |
| `sensor.peak_activity_hour` | The station's busiest hour of the day over the last 7 days | `hourly_activity` (24 hourly values), `peak_hour` |

With bat support on, four bat sensors are added, and `sensor.last_detection` can be a bat. Bird sensors never count bats. See [bats.md](bats.md).

### `sensor.lifetime_species`

The station's life list: every different species it has ever heard. The number only goes up, because the record of first-heard species never shrinks. It's recorded in Home Assistant's long-term statistics, so a history graph shows it climbing over the months. The same number is on `new_species` as the `lifetime_species_count` attribute, for templates.

### Activity and discovery sensors

These sensors describe how busy and varied the station has been. They use BirdWeather's own counts for each period, not the sample of individual detections the integration downloads.

- **`species_diversity`** is the Shannon diversity index for the last 24 hours. It's near 0 when one species dominates and higher when many species are heard in similar numbers. `richness` is the number of species and `evenness` (Pielou's, 0 to 1) is how evenly detections are spread across them.
- **`activity_level`** is today's detection total divided by a typical day, which is the average over the last 30 days. `1.0` is a normal day, `2.0` is twice as busy and `0.5` is half. It's `unknown` until there's a baseline. `detections_today` and `typical_daily_count` are attributes.
- **`new_species_window`** counts species heard for the first time at the station in the last 30 days. Expect it to be high on a new install, and to settle toward 0 once the station knows the local regulars. You can change the 30 days in the [advanced options](advanced.md).
- **`peak_activity_hour`** is the hour of the day the station is busiest, over the last 7 days, shown as a time such as `07:00`. The full 24-hour `hourly_activity` curve is an attribute, for chart cards.
- **`history_start`** (diagnostic) is the time of the station's earliest recorded detection (BirdWeather's `earliestDetectionAt`). It's useful context for the activity and lifetime numbers.

## Binary sensors

| Entity | Device class | On when |
|---|---|---|
| `binary_sensor.extended_silence` | `problem` | The station hasn't reported a single detection in 24 hours |

### `binary_sensor.extended_silence`

A station almost never goes a whole day without hearing a bird. If it does, it's usually offline, unpowered, or its microphone or connection has failed. This sensor turns on when that happens, so you can send yourself a notification. It's based on the last 24 hours of detections, and it's in the device's Diagnostic section.

If a poll fails completely, the integration's sensors become unavailable (see [api.md](api.md#failure-handling)), and this one does too. That way a lost connection reads as "unknown" rather than as a false alarm.

## PUC hardware sensors

On a BirdWeather PUC, the integration also creates sensors for the hardware on board, but only for the groups of readings your station reports. A BirdNET-Pi or other software station gets none. They're created from the first poll's data.

| Entity | Group | Notes |
|---|---|---|
| `sensor.temperature` | environment | °C |
| `sensor.humidity` | environment | % |
| `sensor.barometric_pressure` | environment | hPa |
| `sensor.sound_pressure_level` | environment | dB |
| `sensor.voc` | environment | ppm (the BME688 sensor's bVOCeq) |
| `sensor.air_quality_index` | environment | BSEC IAQ, 0–500 |
| `sensor.light_level` | light | The broadband `clear` channel, a rough measure of brightness |
| `sensor.battery_voltage` | system | V (diagnostic) |
| `sensor.power_source` | system | For example USB-C (diagnostic) |
| `sensor.wifi_signal` | system | dBm (diagnostic) |
| `sensor.sd_card_free` | system | % free, with `free_gb` and `capacity_gb` attributes (diagnostic) |

## The `detections` attribute

Every sensor with a list puts it in an attribute called `detections`. Each item looks like this:

```
{ species, scientific_name, sp_code, image_url, last_seen, rank, ... }
```

BirdWeather records also carry `confidence`, `confidence_band` (low, medium or high), `audio_url` (when audio is turned on), the `alpha` and `alpha6` banding codes, and the reference links (`ebird_url`, `wikipedia_url`, `allaboutbirds_url`, `macaulay_url` and `birdweather_url`). `rank` starts at 1 and is based on that sensor's own ordering:

| Sensor | Rank 1 is | Ordered by |
|---|---|---|
| `recent_detections` | the most recently heard species | `last_seen`, newest first |
| `last_detection` | the most recent detection | `last_seen`, newest first |
| `notable_species` | the most notable species | `notability_score`, highest first |
| `new_species` | the most recent first-time species | `first_seen`, newest first |
| `daily_top_species` | the most detected species in the last 24 hours | 24-hour `count` |
| `yearly_top_species` | the most detected species in the baseline window | baseline `count` |
| `rarest_species` | the rarest species of the last 7 days | `rarity_score`, highest first |
| `watched_species` | the most recently heard watched species | `last_seen`, newest first |

Any of these can be used with the `birdweather-bird-list-card`.

A few things to know:

- `recent_detections` and `notable_species` only cover the last hour and the last 24 hours, from the live detection feed. If the station goes quiet or offline, they empty out, and `notable_species` becomes `unknown`. That's correct for a fixed window.
- `last_detection` doesn't empty out. It keeps the last 50 detections, even through restarts and outages.

### One record per species or per detection

Most sensors have one record per species. If a bird was heard five times, you get one record with `count: 5`, and `last_seen` is the most recent of the five.

`last_detection` is the exception: it has one record per detection, from a saved list of the 50 most recent, newest first. Otherwise the records look the same, so the list card works with both.

Most lists are rebuilt on every poll and go empty when the station is quiet. Two are kept between restarts instead:

- `new_species` lists the most recent species heard for the first time, over the station's whole history. Once the first species is heard, it never goes empty.
- `last_detection` lists the last 50 detections, saved in `.storage/birdweather.<station_id>.recent_events`. It survives restarts and outages, so the last detection is always there, however old it is.

## How rarity is scored

`notable_species` and `rarest_species` score each species against the station's own rarity baseline: BirdWeather's top-species counts over a recent period, 1 month by default (you can change it, see [advanced.md](advanced.md)). The most commonly heard species scores close to 0. A species missing from that period scores 1.0, the same as the rarest one the station has, rather than more.

So a Cooper's Hawk scores as more unusual at a station that rarely hears hawks than at one that hears them every day.

## Tuning notable species

`notable_species` mixes rarity with how recently the bird was heard:

> notability = w × rarity + (1 − w) × recency

Recency is 1.0 for a bird heard right now and falls to 0 for one heard 24 hours ago. You can set `w` with the slider in **Settings → Devices & Services → BirdWeather → Configure**:

- **100% rarity.** The rarest birds, which don't change much.
- **0% rarity.** Whatever was heard most recently, which changes constantly.
- **70% rarity** (the default). Mostly rarity, but a bird heard a few minutes ago can push out one heard many hours ago.

Changes take effect as soon as you save. Saving reloads the integration, so you don't wait for the next poll.

## Confidence

BirdWeather gives each detection a confidence from 0 to 1. The integration turns that into a low, medium or high `confidence_band` on every record, and the cards show it as a colored label.

Two options in the integration's **Configure** dialog use confidence, and they're independent of each other. The first hides low-confidence "maybe" detections from the recent, last, notable and new sensors and from the cards. The second only lets the device triggers fire for confident detections. The 24-hour total and diversity come from BirdWeather's own counts, so the first option doesn't change them.

## What's saved between restarts

`last_detection` and `new_species` are saved, so they come back after a restart. `notable_species` isn't saved on purpose: it only covers the last 24 hours, so after a day with nothing heard it shows `unknown`, with the bird-off icon.

The integration keeps seven files per station in Home Assistant's `.storage` folder (see [architecture.md](architecture.md)):

| File | Contents |
|---|---|
| `birdweather.<station_id>.seen_species` | When each species was first heard |
| `birdweather.<station_id>.last_seen` | When each species was last heard |
| `birdweather.<station_id>.yearly` | The rarity baseline (ranks from BirdWeather's top-species counts) |
| `birdweather.<station_id>.seven_day` | Rarity records for each day, for the 7-day `rarest_species` list |
| `birdweather.<station_id>.recent_events` | The last 50 detections, for `last_detection` |
| `birdweather.<station_id>.species_meta` | Details for each species (codes, scientific names, photo URLs, photo credits, reference links), plus the bats seen, by name |
| `birdweather.<station_id>.last_by_class` | The newest bird and the newest bat, for `last_bird_detection` and `last_bat_detection` |
