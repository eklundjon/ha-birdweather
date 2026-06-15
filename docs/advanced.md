# Advanced configuration

## Tuning windows and cadence

The integration's window lengths and poll cadence have sensible defaults that suit most stations, but all four are exposed under **Settings → Devices & Services → BirdWeather → Configure → Advanced** (a collapsed section — defaults are fine, change only if you know you want to). Changing an option reloads the entry, so new values take effect immediately.

| Option | Default | Range | What it changes |
| --- | --- | --- | --- |
| **Recent window** | 1 hour | 1–24 h | How far back `recent_detections` looks, and how long a species stays "recent" before it can re-fire a new/unusual/watched device trigger. Longer = a fuller recent list but fewer repeat alerts. |
| **Poll interval** | 10 min | 5–60 min | How often the station is polled. Shorter is fresher but more API load. |
| **Rarity baseline window** | 1 month | 1–24 months | Trailing months of BirdWeather `topSpecies` counts used to rank rarity (the `notable`/`rarest` sensors and the `rarity_score` on events). Shorter favors recent frequency; longer trends toward all-time. |
| **New-species momentum window** | 30 days | 7–365 d | Trailing days for the `new_species_window` sensor — how many species were first heard here within the window. Display-only; affects just that sensor. |

> The rarity window is in **months** (not days like the sibling Haikubox integration) because BirdWeather serves it natively as a trailing-period `topSpecies` aggregate, rather than something the integration assembles from per-day history.

Under the hood the integration makes a single detection-feed request per poll — the 1-hour recent window is derived client-side from that same trailing-24 h response. The activity/diversity/history figures come from BirdWeather's native per-period aggregates in one extra GraphQL round-trip.

## Polling

### Changing the polling cadence

The simplest way to change how often the station is polled is the **Poll interval** option above (5–60 minutes). For finer control — a schedule-based cadence, or polling outside that range — turn off automatic polling and drive the refresh yourself:

1. Go to **Settings → Devices & Services**, open the **BirdWeather** entry, use the **⋮** menu → **System options**, and turn **off** *"Enable polling for updates"*. Automatic polling stops.
2. Add an automation that refreshes the data on your chosen schedule. All BirdWeather sensors share one data coordinator, so updating **any one** of them refreshes them all:

```yaml
automation:
  - alias: Refresh BirdWeather every 30 minutes
    triggers:
      - trigger: time_pattern
        minutes: "/30"
    actions:
      - action: homeassistant.update_entity
        target:
          entity_id: sensor.backyard_last_detection
```

This is Home Assistant's built-in, integration-agnostic mechanism for a custom polling interval — see the [HA docs on polling](https://www.home-assistant.io/common-tasks/general/#defining-a-custom-polling-interval).

## Confidence filters

Two independent options (top-level, not in the Advanced section) gate on BirdWeather's per-detection confidence:

- **Hide detections below confidence** — suppresses low-confidence "maybe" detections from the recent / last / notable / new sensors and the cards. The 24-hour total and diversity counts come straight from BirdWeather's own aggregates and are *not* affected.
- **Only alert above confidence** — gates the new-species / unusual-visitor / watched-species device triggers, independent of the hide filter — so you can keep seeing maybes while only being pinged on confident hits.

## Changing the station

A station's ID is its identity (the integration's unique ID), so there's no in-place reconfigure. To point Home Assistant at a different station, remove the BirdWeather entry and add it again with the new station. (Removing an entry also cleans up that station's stored history; see [architecture.md](architecture.md).)
