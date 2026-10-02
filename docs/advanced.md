# Advanced configuration

## Windows and polling

The defaults work for most stations, but you can change them under **Settings → Devices & Services → BirdWeather → Configure → Advanced**. It's a collapsed section. Saving reloads the integration, so new values take effect right away.

| Option | Default | Range | What it does |
| --- | --- | --- | --- |
| **Recent window** | 1 hour | 1–24 h | How far back `recent_detections` looks. It's also how long a species has to be gone before it can set off a new, unusual or watched trigger again. A longer window gives you a longer list and fewer repeat alerts. |
| **Poll interval** | 10 min | 5–60 min | How often the integration checks the station. Shorter is fresher but makes more requests. |
| **Rarity baseline window** | 1 month | 1–24 months | How many months of BirdWeather's top-species counts rarity is measured against. This drives the notable and rarest sensors and the `rarity_score` on events. Shorter favors what's been common recently; longer makes it closer to all-time. |
| **New-species momentum window** | 30 days | 7–365 days | The window for `new_species_window`, which counts the species heard here for the first time in that period. It only affects that one sensor. |

The rarity window is in months, not days as in the Haikubox integration, because BirdWeather provides it directly as a top-species count over a recent period. The integration doesn't have to build it from daily history.

Each poll makes one request for the detection feed. The 1-hour recent window is carved out of that same 24-hour response. The activity, diversity and history numbers come from BirdWeather's own totals for each period, in one more request.

## Polling on your own schedule

The **Poll interval** option covers 5 to 60 minutes. If you want something else, like polling on a schedule, turn off automatic polling and refresh from an automation instead:

1. Go to **Settings → Devices & Services**, open **BirdWeather**, and choose **⋮ → System options**. Turn off **Enable polling for updates**.
2. Create an automation that updates any one BirdWeather sensor on your schedule. All the sensors share the same data, so updating one refreshes them all.

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

This is standard Home Assistant. See [defining a custom polling interval](https://www.home-assistant.io/common-tasks/general/#defining-a-custom-polling-interval) in the HA docs.

## Confidence filters

Two options use BirdWeather's confidence for each detection. They're at the top of the **Configure** dialog, not under **Advanced**, and they're independent of each other:

- **Hide detections below confidence** leaves low-confidence "maybe" detections out of the recent, last, notable and new sensors and the cards. The 24-hour total and diversity come straight from BirdWeather's own counts, so this doesn't change them.
- **Only alert above confidence** stops the new-species, unusual-visitor and watched-species triggers from firing below that confidence. You can keep seeing the maybes and only get notified about confident detections.

## Changing the station

The station ID is the integration entry's identity, so you can't switch an entry to a different station. **Reconfigure** only changes bat support (see [bats.md](bats.md)). To use a different station, remove the BirdWeather entry and add it again with the new station. Removing an entry also deletes that station's saved history (see [architecture.md](architecture.md)).
