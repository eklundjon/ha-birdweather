# BirdWeather for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.12+-blue.svg?logo=homeassistant)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Home Assistant custom integration for [BirdWeather](https://www.birdweather.com/) stations (PUC, BirdNET-Pi, and other registered stations). Surfaces recent detections, daily and rolling species counts, activity and diversity trends, and highlights unusual visitors — all with bird photos and custom Lovelace cards.

It reads the **public** BirdWeather GraphQL API anonymously — no account or API token is needed for any station whose owner has made it public.

## Features

- **Recent detections** — species heard in the last hour, updated every few minutes
- **Last detection** — persists the most recently heard bird, never goes unknown between detections
- **Rolling 24-hour counts** — true total detections and top species over the trailing 24 hours
- **Species diversity (24 h)** — Shannon index over the last day, with richness and evenness attributes
- **Activity vs. typical** — how busy the station is right now relative to its own 30-day average (1.0 ≈ a normal day)
- **Notable species** — most unusual recent visitor, by a tunable blend of rarity (vs. the station's trailing baseline) and recency
- **New species** — flags species new to the station, plus a rolling "new species in the last 30 days" momentum count
- **Bird-detail sensors** — top species (baseline), rarest species (7 d), lifetime species count
- **Detection history start** — diagnostic timestamp of the station's earliest recorded detection
- **Extended silence** — diagnostic problem sensor that flags when a station goes a full day without reporting
- **Custom Lovelace cards** — a bird photo card and a ranked list card, with optional per-row links to **eBird**, **All About Birds**, **Macaulay Library**, and **BirdWeather**
- **Species details** — expand a species in the list card for a Wikipedia description (fetched on demand; tap it to open the full article), its alpha banding code, and the reference links above
- **Play the call** — a play button on the bird card and in the list card's detail plays the detection's recording (soundscape) right in the browser
- **Daily activity rhythm** — a **Peak activity hour** sensor (the station's "dawn chorus" peak) with a 24-hour `hourly_activity` curve for chart cards, plus a per-species **hourly sparkline** (▁▂▅█) in the list card's detail view showing when each bird is most active
- **Historical trends (no Grafana)** — backfills Home Assistant's native **long-term Statistics** with the station's *true* daily history — detections per day and species per day, all the way back to its first recorded day — so HA's built-in Statistics graph card shows real multi-month trends out of the box
- **Automations** — device triggers for new-species, unusual-visitor, and watched-species detections
- **Watched species** — pick (or type) species to be alerted about; a device trigger fires when one is heard, plus a **Watched species** sensor listing the ones your station has recorded (drop it into the list card for a "Birds of interest" view)
- **Confidence controls** — optional thresholds to hide low-confidence "maybe" detections from the feed and to gate alerts on confident hits only (independent, so you can see maybes but only be pinged on sure things); the cards show a low/medium/high confidence band
- **PUC hardware sensors** — for BirdWeather **PUC** stations, onboard environment readings (temperature, humidity, barometric pressure, sound level, air quality, light) and device-health diagnostics (battery voltage, power source, Wi-Fi signal, SD-card free) — created automatically, and only for the hardware your station actually reports (a BirdNET-Pi gets none)

## Quick start

### Install

**HACS (recommended)**

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=eklundjon&repository=ha-birdweather&category=integration)

Click the badge to open HACS in your Home Assistant with this repository pre-filled, then **Download** and restart. Or add it manually:

1. In **HACS**, open the **⋮** menu (top right) → **Custom repositories**
2. Add `https://github.com/eklundjon/ha-birdweather`, type **Integration**, then **Add**
3. Search HACS for **BirdWeather**, open it, and click **Download**
4. Restart Home Assistant

**Manual**

1. Copy the `custom_components/birdweather` folder into your HA `config/custom_components/` directory
2. Restart Home Assistant

### Configure

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **BirdWeather**.
3. Pick a nearby public station from the list, type a name to search, or paste a numeric **station ID** directly.

> **Finding your station ID.** On [app.birdweather.com](https://app.birdweather.com), open your station — the ID is the number in the URL (`.../stations/<id>`). The station must be **public** for the integration to read it.

A device is created and named after the station, with the sensors above plus an "extended silence" binary sensor.

### Add a card

Both custom cards register automatically — no Lovelace resource setup required. The simplest "show me a bird" card:

```yaml
type: custom:birdweather-bird-card
entity: sensor.<station>_last_detection
```

A ranked list (e.g. top species over the last 24 hours):

```yaml
type: custom:birdweather-bird-list-card
entity: sensor.<station>_daily_top_species
```

### Historical trends

The integration backfills HA's long-term Statistics with the station's true daily history. View it with the built-in **Statistics graph** card (no Grafana needed) — the statistic IDs are `birdweather:station_<id>_daily_detections` (detections/day, totals per day/week/month) and `birdweather:station_<id>_daily_species` (species/day):

```yaml
type: statistics-graph
title: Detections per day
chart_type: bar
period: day
stat_types: [sum]
entities:
  - birdweather:station_<id>_daily_detections
```

## Options

After setup, open the integration's **Configure** dialog to tune:

- **Notability rarity weight** — how much the "notable species" pick leans on rarity vs. recency (100% = pure rarity; default 70%).
- **Unusual-visitor days** — how long a known species must go unheard before its reappearance counts as an unusual visitor (default 30 days).
- **Hide detections below confidence** — suppress low-confidence "maybe" detections from the recent / last / notable / new sensors and the cards (0% = show everything, the default). The 24-hour **total** and **diversity** counts come straight from BirdWeather's own aggregates and are *not* affected by this filter — they always reflect the station's own confidence floor.
- **Only alert above confidence** — don't fire the new-species, unusual-visitor, or watched-species triggers below this confidence (0% = alert on any, the default). Independent of the hide filter, so you can keep seeing maybes while only being pinged on confident hits.
- **Watched species** — choose species (from a pick-list of ones your station has detected, and/or a free-text list for ones it hasn't) to be alerted about. When a watched species is heard, the **"Watched species detected"** device trigger fires — wire it to a notification in the automation editor.

## Troubleshooting

**A bird photo looks oddly cropped (a beak, tail, or head cut off).**
The photos come from BirdWeather, which serves one square crop of a contributor
photo per species — and a few are cropped tightly at the source. The cards
always show the *whole* image and never crop it further (the soft blurred edges
you may see are just fill), so a clipped subject means BirdWeather's own image is
cropped that way. It can't be corrected from Home Assistant; if a photo looks
wrong, it's worth reporting to BirdWeather.

**A card shows a 🐦 placeholder instead of a photo.**
BirdWeather has no image for that species yet, or it failed to load; it appears
once a photo is available and the next poll caches it.

**A card looks stale right after updating the integration.**
Hard-refresh the dashboard — the card JavaScript is cached by your browser and
only re-fetched when the integration version changes.

## Attribution & data licensing

This integration surfaces data from the **BirdWeather** public API — detections,
species counts, and the bird photos served from its media CDN. BirdWeather data is
powered by [BirdNET](https://birdnet.cornell.edu/); if you use it for research,
please cite BirdNET:

> Kahl, S., Wood, C. M., Eibl, M., & Klinck, H. (2021). BirdNET: A deep learning
> solution for avian diversity monitoring. *Ecological Informatics*, 61, 101236.

Bird photographs are served by BirdWeather and may be individually licensed by
their contributors; review BirdWeather's terms before any redistribution or
commercial use.

## License

MIT License — see [LICENSE](LICENSE) for details. This applies to the
integration's **code**. The bird data and photos it surfaces (BirdWeather /
BirdNET and contributors) are covered by their own terms, not by the MIT license.
