# Troubleshooting

## Config flow can't find the station

During setup the integration looks the station up in BirdWeather's GraphQL API, and the error tells you which kind of failure it was:

- **"No public station was found with that ID."** — the API answered but didn't recognise the station (wrong ID, or a station that isn't public).
- **"Could not reach the BirdWeather API. Please try again."** — the request got no answer at all (a network/transport failure). That points at connectivity on the HA host, not the station ID.

Two things to check for the "no public station" case:

1. **Wrong station ID.** On [app.birdweather.com](https://app.birdweather.com), open your station — the ID is the number in the URL (`.../stations/<id>`). You can also pick a nearby station from the list in the setup dialog, or type a name to search, instead of pasting an ID.
2. **Station isn't public.** The integration reads the public API, so the station must be public for the lookup to succeed.

## Sensors show `0` or `unknown` right after install

Each poll fetches a trailing-24 h detection window plus BirdWeather's native per-period aggregates, so most sensors populate on poll 1 if the station has recent activity. What to expect:

- `recent_detections` — populates on the first poll that returns detections in the last hour; empty between active hours.
- `last_detection`, `notable_species`, `new_species` — populate on the first poll that returns detections in the last 24 hours. `last_detection` then persists (rolling event cache; survives restarts/outages) and `new_species` persists (lifetime log); `notable_species` is an observation window and goes `unknown` after 24 h with nothing detected.
- `daily_count`, `daily_top_species`, `species_diversity`, `activity_level`, `new_species_window`, `lifetime_species` — come from BirdWeather's native counts; populate on the first successful poll (`activity_level` is `unknown` until the trailing-30-day baseline has data).
- `notable_species`, `rarest_species`, `yearly_top_species` — score against the rarity baseline (`topSpecies` over the trailing window), fetched once per day; available from the first poll.
- `peak_activity_hour` — from the trailing-7-day time-of-day histogram, fetched once per day.
- PUC hardware sensors — created on the first poll, and only for the suites your station reports (a non-PUC station gets none); they appear after a restart if the station gains a PUC later.

## `last_detection` is fine but `notable_species` is `unknown`

These behave differently on purpose (see #62):

- **`last_detection`** persists — it reads a rolling cache of the most recent detection events (`.storage/birdweather.<station_id>.recent_events`), rehydrated on startup, so it survives restarts *and* outages. It's only `unknown` before the station's very first detection.
- **`notable_species`** is deliberately *not* persisted — it means "most notable in the last 24 h," so it drops to `unknown` (with the bird-off icon) when nothing has been detected in 24 h. During an outage that's the expected signal — check the BirdWeather app to confirm the station is hearing birds.

## The "play the call" button does nothing

Audio is **off by default**; enable it under **Configure → Audio**. Even then, if your BirdWeather station has audio sharing turned off its soundscapes are silent — the button appears but plays nothing (the integration streams BirdWeather's clip directly and can't detect a silent one). FLAC also may not play in some browsers/contexts.

## Bird counts dropped after upgrading

On a bat-edition PUC, earlier versions counted bats as birds. Bird counts now leave bats out, so the 24-hour totals, top species, lifetime species, the activity curve and the long-term statistics can drop when you upgrade, and the statistics graph shows a one-time step. Turn on **Bat support** with **Reconfigure** to see the bats on their own sensors. See [bats.md](bats.md).

## Custom cards don't appear in the dashboard editor

The integration registers `birdweather-bird-card` and `birdweather-bird-list-card` automatically on startup; you don't need to add them as Lovelace resources. If the picker doesn't list them:

1. Restart Home Assistant once. Card registration runs during integration setup.
2. Hard-refresh your dashboard (browser reload bypassing cache, e.g. **Shift+Cmd+R** / **Ctrl+F5**). The card JS is cached aggressively.
3. Check **Settings → System → Logs** for `birdweather` setup errors — if setup failed, the cards never got registered.

## Cards show "Custom element doesn't exist" after a restart

Home Assistant starts serving the dashboard before integrations like this one have finished loading. A browser or the Home Assistant app that reconnects during a restart can load the dashboard in that gap, before the cards exist. On older Apple devices (Safari and iPad web views before iPadOS 26), the cards could also fail to appear on every reload, because of a compatibility layer Home Assistant loads on those browsers.

To handle both, the integration puts a small loader at `config/www/birdweather-card-loader.js` and adds it to your dashboard resources (**Settings → Dashboards → ⋮ → Resources**). The loader waits for the integration to finish loading and then brings the cards in, so they appear without a refresh. Please don't delete that resource. It's removed automatically when you remove your last BirdWeather station.

If you still see the error:

1. **YAML dashboards** (`lovelace: mode: yaml`) have to list the loader themselves:
   ```yaml
   lovelace:
     mode: yaml
     resources:
       - url: /local/birdweather-card-loader.js
         type: module
   ```
   Right after an upgrade, a YAML dashboard may show the old version of the cards once. A force-refresh fixes it.
2. **First restart after installing.** Home Assistant only serves files from `config/www` if that folder existed when it started. If the integration had to create it, the loader starts working after your next restart.

## A card looks stale right after updating the integration

The card JavaScript is cached by your browser and only re-fetched when the integration version changes; an already-open dashboard tab keeps running the old JS until it reloads. Hard-refresh the dashboard once after upgrading.

## A bird photo looks oddly cropped, or shows a placeholder

Photos come from BirdWeather, which serves one square crop per species — and a few are cropped tightly at the source. The cards always show the *whole* image (the soft blurred edges are fill), so a clipped subject means BirdWeather's own image is cropped that way. A bird placeholder means BirdWeather has no image for that species yet, or it failed to load; it appears once a photo is available and the next poll caches the URL.

## Sensor entity IDs don't match the docs

The IDs in these docs use a station named "Backyard." If your station has a different name, sensors are prefixed with `sensor.<your_device_name>_*`. The suffix (`last_detection`, `notable_species`, etc.) is stable across installs.

## Filing a bug report

Open the BirdWeather device page and use **⋮ → Download diagnostics** to attach a redacted snapshot of the integration's state (the station ID and name are redacted, so it's safe to share). It includes the latest poll's data and a short coordinator summary.
