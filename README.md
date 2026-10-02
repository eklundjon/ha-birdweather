# BirdWeather for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2025.4+-blue.svg?logo=homeassistant)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

This is a Home Assistant integration for [BirdWeather](https://www.birdweather.com/) stations: PUCs, BirdNET-Pis, and any other registered station. It shows what the station has been hearing, keeps daily and rolling species counts, tracks activity and diversity, points out unusual visitors, and comes with two dashboard cards that show bird photos.

**Before you start:**

- **The station has to be public.** The integration reads BirdWeather's public API without logging in, so you don't need an account or an API token, but it can't see a private station.
- **You'll need the station's ID**, or you can pick a nearby public station from a list during setup. The ID is the number at the end of the station's URL on [app.birdweather.com](https://app.birdweather.com) (`.../stations/<id>`).
- **Home Assistant 2025.4 or later.**
- On a bat-edition PUC, leave **Bat support** ticked during setup.

## Features

- **Recent detections.** Species heard in the last hour, updated every few minutes.
- **Last detection.** The most recent bird the station heard. It never goes back to unknown between detections.
- **24-hour counts.** True total detections and top species over the last 24 hours.
- **Species diversity.** A diversity score for the last 24 hours (the Shannon index), with species richness and evenness as attributes.
- **Activity vs. typical.** How busy the station is right now compared with its own 30-day average. 1.0 is a normal day.
- **Notable species.** The most unusual recent visitor, scored on how rare it is against the station's own history and how recently it was heard. You can adjust the balance between the two.
- **New species.** Species heard for the first time at the station, plus a count of how many were new in the last 30 days.
- **Top, rarest and lifetime species.** The station's most common species, its rarest species of the last 7 days, and the number of species it has ever recorded.
- **Detection history start.** A diagnostic timestamp of the station's earliest recorded detection.
- **Extended silence.** A diagnostic problem sensor that turns on when the station goes a full day without reporting.
- **Dashboard cards.** A single-bird photo card and a ranked list card, with optional links on each row to eBird, All About Birds, the Macaulay Library and BirdWeather.
- **Species details.** Expand a species in the list card for a Wikipedia description (fetched when you open it; tap it for the full article), its alpha banding code, and the same reference links.
- **Play the call** (beta). A play button on the bird card and in the list card's details plays the detection's recording (its soundscape) in your browser. It's off by default; turn it on in the integration's options. If the station has audio sharing turned off, its soundscapes are silent, so the button plays nothing. The integration streams BirdWeather's clip directly and can't tell that a clip is silent.
- **Daily activity rhythm.** A **Peak activity hour** sensor (the station's dawn-chorus peak) with a 24-hour `hourly_activity` curve for chart cards, plus a small hourly chart (▁▂▅█) for each species in the list card's details, showing when that bird is most active.
- **Long-term history.** The integration loads the station's real daily history into Home Assistant's Statistics, detections per day and species per day all the way back to its first day, so the built-in Statistics graph card can chart months of trends. No Grafana required.
- **Automations.** Device triggers for new species, unusual visitors and species you're watching for, plus blueprints for photo notifications and for playing a call on a speaker.
- **Watched species.** Pick (or type) species you want to hear about. A device trigger fires when one is heard, and a **Watched species** sensor lists the ones your station has recorded, which you can put in the list card for a "birds of interest" view.
- **Confidence controls.** Two optional thresholds: one hides low-confidence "maybe" detections from the feed, and one only fires alerts for confident detections. They're independent, so you can still see the maybes but only get notified about sure things. The cards show a low, medium or high confidence label.
- **Bats.** On a bat-edition PUC, turn on bat support for bat sensors (the last bat, and bats in the last 24 hours), a bat list card that shows each bat's reported behavior, and a "bat activity" trigger. Bird counts never include bats ([details](docs/bats.md)).
- **PUC hardware sensors.** On a BirdWeather PUC, onboard environment readings (temperature, humidity, air pressure, sound level, air quality and light) and device-health diagnostics (battery voltage, power source, Wi-Fi signal and free SD card space). They're created automatically, and only for the hardware your station reports, so a BirdNET-Pi gets none.

## Quick start

### Install

**HACS (recommended)**

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=eklundjon&repository=ha-birdweather&category=integration)

Click the badge to open this repository in HACS, click **Download**, and restart Home Assistant. Or add it by hand:

1. In **HACS**, open the **⋮** menu (top right) and choose **Custom repositories**.
2. Add `https://github.com/eklundjon/ha-birdweather` with type **Integration**, then click **Add**.
3. Search HACS for **BirdWeather**, open it, and click **Download**.
4. Restart Home Assistant.

**Manual**

1. Copy the `custom_components/birdweather` folder into your Home Assistant `config/custom_components/` folder.
2. Restart Home Assistant.

### Add the integration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **BirdWeather**.
3. Pick a nearby public station from the list, type a name to search for one, or paste a station ID.
4. Choose whether to turn on **Bat support**. It's already ticked for a bat-edition PUC (see [docs/bats.md](docs/bats.md)). You can change it later with **Reconfigure**.

To find your station ID, open your station on [app.birdweather.com](https://app.birdweather.com). The ID is the number at the end of the URL (`.../stations/<id>`). The station has to be public for the integration to read it.

The integration creates a device named after the station, with the sensors above and an "extended silence" binary sensor.

### Add a card

The cards install themselves, so there's nothing to add under dashboard resources. (The integration adds a small `/local/birdweather-card-loader.js` resource itself, so the cards also load on pages opened while Home Assistant is still starting. If your dashboards are in YAML mode, you need to add that resource yourself. See [troubleshooting](docs/troubleshooting.md#cards-show-custom-element-doesnt-exist-after-a-restart).) The simplest card is:

```yaml
type: custom:birdweather-bird-card
entity: sensor.<station>_last_detection
```

A ranked list, here the top species of the last 24 hours:

```yaml
type: custom:birdweather-bird-list-card
entity: sensor.<station>_daily_top_species
```

### Long-term history

To chart the station's history, add a **Statistics graph** card. The statistic IDs are `birdweather:station_<id>_daily_detections` (detections per day, which can also be totaled by week or month) and `birdweather:station_<id>_daily_species` (species per day).

```yaml
type: statistics-graph
title: Detections per day
chart_type: bar
period: day
stat_types: [sum]
entities:
  - birdweather:station_<id>_daily_detections
```

### Automations

The automation editor offers device triggers (**When → Device**) for new species, unusual visitors and watched species, and there are four blueprints for photo notifications and for playing a call on a speaker, each with a one-click import badge. See [docs/automations.md](docs/automations.md).

## Options

After setup, open the integration's **Configure** dialog for the notability balance, the unusual-visitor threshold, the two confidence filters, audio, watched species, and (under **Advanced**) the time windows and poll interval. Every option, with its default and range, is in [docs/advanced.md](docs/advanced.md).

## Documentation

| Topic | Doc |
|---|---|
| Every sensor, the `detections` attribute, how rarity is scored, what's saved between restarts | [docs/sensors.md](docs/sensors.md) |
| The two cards, YAML examples, tap actions, a sample dashboard | [docs/cards.md](docs/cards.md) |
| Device triggers, the `birdweather_event` event, notification blueprints | [docs/automations.md](docs/automations.md) |
| Bat support: what it adds, and how bats are kept out of bird counts | [docs/bats.md](docs/bats.md) |
| Every option and its default, polling on your own schedule, changing the station or bat support | [docs/advanced.md](docs/advanced.md) |
| Setup errors, the first poll after install, sensors that go offline, cards not updating, diagnostics | [docs/troubleshooting.md](docs/troubleshooting.md) |
| Which BirdWeather queries the integration makes, how often, and what happens when they fail | [docs/api.md](docs/api.md) |
| How the code is organized | [docs/architecture.md](docs/architecture.md) |
| Development setup, tests, CI, the refactor smoke test | [docs/contributing.md](docs/contributing.md) |

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md) for setup errors, sensors that are empty or `unknown`, cards that don't load or look out of date, oddly cropped photos, and how to download diagnostics for a bug report.

## Attribution & data licensing

**BirdWeather data and photos.** Detections, species counts and bird photos (served from BirdWeather's media CDN) come from the BirdWeather public API, which is powered by [BirdNET](https://birdnet.cornell.edu/). If you use the data for research, please cite BirdNET:

> Kahl, S., Wood, C. M., Eibl, M., & Klinck, H. (2021). BirdNET: A deep learning
> solution for avian diversity monitoring. *Ecological Informatics*, 61, 101236.

The bird photos are served by BirdWeather and may be licensed individually by the people who took them. Check BirdWeather's terms before redistributing them or using them commercially.

## License

The code is released under the MIT License (see [LICENSE](LICENSE)). The bird data and photos it displays (from BirdWeather, BirdNET and photo contributors) are covered by their own terms, not by the MIT license.
