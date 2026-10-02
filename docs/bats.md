# Bats

BirdWeather's bat-edition PUC hears bats as well as birds, and BirdWeather labels each species as a bird or a bat. This page covers what the integration does with them.

## Turning it on

After you pick a station during setup, a second step asks about **Bat support**. It's ticked already if the station is a bat-edition PUC. To change it later, open the integration and choose **Reconfigure**.

- **On:** bats are fetched on their own and get their own sensors and events (below).
- **Off:** bats aren't fetched at all, and turning it off removes the bat sensors.

Either way, **bird figures never include bats**. The integration asks BirdWeather for birds only when it fetches the detection feed and the totals behind the 24-hour counts, top species, diversity, rarity, lifetime and new species, activity, the time-of-day curve and the long-term statistics. On a bat-edition PUC, bird counts drop when you upgrade, and the long-term statistics show a one-time step.

## Sensors

With bat support on, four sensors are added:

| Sensor | State | `detections` attribute |
|---|---|---|
| `sensor.last_bird_detection` | the most recent bird | that detection |
| `sensor.last_bat_detection` | the most recent bat | that detection |
| `sensor.bat_count_today` | bat detections in the last 24 hours | none |
| `sensor.bats_today` | bat species heard in the last 24 hours | the bats, by count |

The counts are BirdWeather's own totals over the trailing 24 hours, the same as for **Total detections (24 h)**.

`sensor.last_detection` stays as it is: the most recent detection of either kind, so it shows a bat at night and a bird by day. Use the bird and bat sensors when you want only one.

Records for bats carry `"classification": "bat"` and the bat's reported behavior: `behavior` (for example "Search/Clutter"), `behavior_code` (`bat_search_clutter`) and `behavior_confidence`, how sure BirdWeather's classifier is of the behavior. They have no eBird, All About Birds or Macaulay Library links (those are bird references), but keep the Wikipedia and BirdWeather links.

## Cards

For a bat list, point a list card at the bats sensor:

```yaml
type: custom:birdweather-bird-list-card
entity: sensor.bats_today
title: Bats
```

For a bird list that stays birds-only, use any of the existing bird sensors. For a photo of the last bat, point a bird card at `sensor.last_bat_detection`.

The cards show a bat's behavior under its name on the photo card, and among the details when you expand a row in the list card, for example "Search/Clutter · 60%".

## Automations

- **New species** and **Watched species** fire for bats as they do for birds. The event's `classification` field tells them apart, and bat events carry the behavior fields. For a bat, `lifetime_species_count` counts bat species.
- **Bat activity started** (`bat_activity`) fires when bats are heard after at least 60 minutes without one. Its `count` is the number of bat detections since the previous one, and `quiet_minutes` is how long the quiet spell lasted. It doesn't fire for every bat, and it doesn't fire on the first poll after setup, when there's no earlier bat to measure from.
- **Only alert above confidence** applies to bat events too. It compares the identification confidence, not `behavior_confidence`.
- **Unusual visitor** stays birds-only, because it's based on rarity.

Every `birdweather_event` now has a `classification` field, `bird` or `bat`.

## Audio

Bat recordings are ultrasonic and play as silence without processing, so the play button isn't shown for bats yet. Making them audible is planned.

## How it works

- The integration fetches two detection feeds each poll: up to 300 bird detections and, with bat support on, up to 100 bat detections, each filtered to its class by BirdWeather. A busy night of bats can't push the birds out of their feed.
- The bird totals use BirdWeather's class filter too, and today's bat totals come back in the same request.
- BirdWeather often reports a group rather than a species, such as "Bats" or "Vesper Bats". Those count as bats like any other.
- BirdWeather's classifier uses the station's location to decide which species are plausible. If the station's location is wrong in the BirdWeather app, expect generic "Bats" and few bird species.
