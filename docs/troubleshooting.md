# Troubleshooting

## Setup can't find the station

During setup the integration looks the station up in BirdWeather's API. The error tells you which way it failed:

- ***No public station was found with that ID.*** BirdWeather answered but didn't recognize the station. Either the ID is wrong, or the station isn't public.
- ***Could not reach the BirdWeather API. Please try again.*** The request got no answer at all. That's a network problem on the Home Assistant machine, not a problem with the station ID.

For the first error, check two things:

1. **The station ID.** Open your station on [app.birdweather.com](https://app.birdweather.com). The ID is the number at the end of the URL (`.../stations/<id>`). You can also pick a nearby station from the list in the setup dialog, or type a name to search for it, instead of pasting an ID.
2. **Whether the station is public.** The integration reads BirdWeather's public API, so the station has to be public.

## A new station has no detections yet

The integration still sets up its sensors, including any PUC hardware readings. Recent detections shows zero, and last detection stays `unknown` until BirdWeather has a public detection for the station. An empty history is fine, including after a Home Assistant restart.

## Sensors show `0` or `unknown` right after install

Each poll fetches the last 24 hours of detections plus BirdWeather's own totals for each period, so most sensors fill in on the first poll if the station has been active. What to expect:

- `recent_detections` fills in on the first poll that finds detections in the last hour. It's empty between active hours.
- `last_detection`, `notable_species` and `new_species` fill in on the first poll that finds detections in the last 24 hours. After that, `last_detection` keeps its value (from its saved list of recent detections, through restarts and outages) and so does `new_species` (from the saved record of first-heard species). `notable_species` only covers the last 24 hours, so it goes to `unknown` after 24 hours with nothing heard.
- `daily_count`, `daily_top_species`, `species_diversity`, `activity_level`, `new_species_window` and `lifetime_species` come from BirdWeather's own counts and fill in on the first successful poll. `activity_level` stays `unknown` until there's a 30-day baseline.
- `notable_species`, `rarest_species` and `yearly_top_species` are scored against the rarity baseline (BirdWeather's top species over the baseline window), which is fetched once a day. They're available from the first poll.
- `peak_activity_hour` comes from the station's time-of-day activity over the last 7 days, fetched once a day.
- The PUC hardware sensors are created on the first poll, and only for the groups of readings your station reports, so a station that isn't a PUC gets none. If a station starts reporting them later, they appear after a restart.

## `last_detection` is fine but `notable_species` is `unknown`

These behave differently on purpose:

- **`last_detection`** reads a saved list of the most recent detections (`.storage/birdweather.<station_id>.recent_events`), loaded again on startup, so it survives restarts and outages. It's only `unknown` before the station's very first detection.
- **`notable_species`** isn't saved, on purpose. It's the most notable bird of the last 24 hours, so it goes to `unknown` (with the bird-off icon) when nothing has been heard for 24 hours. During an outage, that's the sign to expect. Check the BirdWeather app to see whether the station is still hearing birds.

## The "play the call" button does nothing

Audio is off by default. Turn it on under **Configure → Audio**. Even then, if your station has audio sharing turned off, its soundscapes are silent: the button appears but plays nothing, since the integration plays BirdWeather's clip as it is and can't tell that it's silent. FLAC also may not play in some browsers.

## Bird counts dropped after upgrading

On a bat-edition PUC, earlier versions counted bats as birds. Bird counts now leave bats out, so the 24-hour totals, top species, lifetime species, the activity curve and the long-term statistics can drop when you upgrade, and the statistics graph shows a one-time step. Turn on **Bat support** with **Reconfigure** to see the bats on their own sensors. See [bats.md](bats.md).

## The cards don't appear in the dashboard editor

The integration adds `birdweather-bird-card` and `birdweather-bird-list-card` itself when it starts, so you don't need to add them as dashboard resources. If the card picker doesn't list them:

1. Restart Home Assistant once. The cards are added while the integration sets up.
2. Force-refresh the dashboard (**Shift+Cmd+R** or **Ctrl+F5**). Browsers hold on to the card code.
3. Look in **Settings → System → Logs** for `birdweather` setup errors. If setup failed, the cards were never added.

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

## A card looks out of date right after updating the integration

Your browser caches the card code and only fetches it again when the integration's version changes, and a dashboard tab that's already open keeps running the old code until it reloads. Force-refresh the dashboard once after upgrading.

## A bird photo looks oddly cropped, or shows a placeholder

Photos come from BirdWeather, which serves one square crop for each species, and a few are cropped tightly at the source. The cards always show the whole image (the soft blurred edges are just fill), so a clipped bird means BirdWeather's own image is cropped that way. A bird placeholder means BirdWeather has no image for that species yet, or it didn't load. It shows up once a photo is available and the next poll saves its address.

## Sensor entity IDs don't match the docs

The IDs in these docs are for a station named "Backyard". If your station has a different name, its sensors start with `sensor.<your_device_name>_` instead. The end of the ID (`last_detection`, `notable_species` and so on) is the same on every install.

## Filing a bug report

Open the BirdWeather device page and choose **⋮ → Download diagnostics**. The download is a snapshot of the integration's state, including the latest poll's data and a short coordinator summary. The station ID and name are removed, so it's safe to attach.
