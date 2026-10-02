# Custom cards

The integration comes with two dashboard cards. They install themselves, so there's nothing to add under dashboard resources.

- [`birdweather-bird-card`](#birdweather-bird-card) shows one bird: photo, name and how long ago it was heard.
- [`birdweather-bird-list-card`](#birdweather-bird-list-card) shows a ranked list of birds. Tap a row for details.
- [Dashboard example](#dashboard-example)
- [Visual editor](#visual-editor)
- [Theming](#theming)
- [Troubleshooting](#troubleshooting)

Both cards need Home Assistant 2025.4 or later, the same as the integration. They draw the same way as the Haikubox integration's cards, because they're generated from them by `scripts/sync-cards.sh`, with BirdWeather's reference link added back by hand (see [contributing.md](contributing.md)).

---

## `birdweather-bird-card`

Shows a single bird with its photo, common and scientific names, and how long ago it was heard.

```yaml
type: custom:birdweather-bird-card
entity: sensor.backyard_notable_species
grid_options:
  columns: 6
  rows: 4
```

The card adjusts to whatever size you give it:

- **Tall or square cards** put the photo on top, filling the card's width, and the text centered underneath. BirdWeather's photos are square, so a blurred copy of the photo fills the space on either side.
- **Wide cards** (wider than about 3:2) put the photo on the left and the text on the right.
- **Text size** grows and shrinks with the card.

The card works with any BirdWeather sensor that has a `detections` list. That's eight sensors: `recent_detections`, `last_detection`, `daily_top_species`, `notable_species`, `new_species`, `yearly_top_species`, `rarest_species` and `watched_species`. With [bat support](bats.md) on, `last_bird_detection`, `last_bat_detection` and `bats_today` work too. The sensors that are just a number (`daily_count`, `lifetime_species`, `species_diversity`, `activity_level`, `new_species_window`, `history_start` and `peak_activity_hour`) have no list, so they aren't offered. The card shows the top-ranked bird from the list. If the list is empty, it says "No recent detections."

The "5m ago" label updates every minute, so it stays accurate between polls.

### Buttons on the photo

Two round buttons sit at the top corners of the photo, clear of the photo credit at the bottom:

- **▶** (top left) plays the bird's call, when audio is turned on in the integration's options and a recording exists. See [Play the call](#play-the-call-audio).
- **ⓘ** (top right) opens a popup with the list card's full details view for this bird: a larger photo, the Wikipedia description, the confidence, the activity chart, the reference links and the play button. Hide it with `show_details: false`. Click outside the popup or press **Esc** to close it.

### Showing a different bird (`position`)

The card normally shows the #1 bird. Set `position` to show a different one: `1` is the top, `2` is second, and so on. This lets you stack a few cards that each show a different bird from the same sensor:

```yaml
- type: custom:birdweather-bird-card
  entity: sensor.backyard_daily_top_species
  position: 1
- type: custom:birdweather-bird-card
  entity: sensor.backyard_daily_top_species
  position: 2
```

If there aren't that many birds in the list, the card shows its empty message.

### `last_detection` is different

Most sensors list one record per species. `last_detection` lists individual detections from a saved list, so a card pointed at it shows the single most recent detection, and keeps showing it through restarts and outages. See [sensors.md](sensors.md#one-record-per-species-or-per-detection).

Since `last_detection` never goes blank, it can't tell you the station has gone silent. For that, watch for `notable_species` going `unknown` or `recent_detections` staying at 0.

### Tap action

What happens when you tap the card:

- `more-info` (the default) opens the sensor's more-info dialog.
- `show-list` opens a popup with the [list card](#birdweather-bird-list-card) for the same sensor.
- `navigate` goes to another dashboard page.
- `url` opens a web page.
- `none` does nothing.

`navigation_path` and `url_path` can include these tokens, which are filled in from the bird the card is showing:

| Token | Replaced with | Example |
|--|--|--|
| `{species}` | Common name | `Downy Woodpecker` |
| `{species_slug}` | Common name with underscores for spaces | `Downy_Woodpecker` |
| `{sp_code}` | eBird species code | `dowwoo` |
| `{scientific_name}` | Scientific name | `Picoides pubescens` |

Open the bird's eBird page:

```yaml
type: custom:birdweather-bird-card
entity: sensor.backyard_last_detection
tap_action:
  action: url
  url_path: https://ebird.org/species/{sp_code}
```

The visual editor has a **Tap action** dropdown (More info, Show species list, Navigate, Open URL, None) and a field for the path.

---

## `birdweather-bird-list-card`

A ranked list of birds. Tap a row to expand it. Works with any sensor that has a [`detections` list](sensors.md#the-detections-attribute).

```yaml
type: custom:birdweather-bird-list-card
entity: sensor.backyard_yearly_top_species
title: Top Species               # optional; defaults to the sensor's name
top: 10                          # how many birds to show (default 10)
row_size: small                 # small, medium or large (default small)
show_ebird: false               # eBird button on each row (default false)
show_allaboutbirds: false       # All About Birds button on each row (default false)
show_macaulay: false            # Macaulay Library button on each row (default false)
show_birdweather: false         # BirdWeather button on each row (default false)
show_confidence: true           # confidence label when a row is expanded (default true)
show_description: true          # Wikipedia description when a row is expanded (default true)
show_activity: true             # daily activity chart when a row is expanded (default true)
show_audio: true                # play button when a row is expanded (default true)
grid_options:
  columns: 12
  rows: 4
```

Each row shows the bird's rank, photo, and common and scientific names. Tap a row to expand it into a larger photo, the scientific name, a short Wikipedia description (tap it to open the article), how many times it was heard and when it was last heard (where those are known), a low, medium or high confidence label, a daily activity chart ("most active ~7h"), a play button, and reference links. Tap again to close it. Only one row is open at a time.

### Row size

`row_size` makes the rows bigger or smaller: `small` (the default), `medium` or `large`. The photo, spacing and text all grow together. It's also a dropdown in the editor.

### Reference links

Each row can link to the bird's page on eBird, All About Birds, the Macaulay Library and BirdWeather. BirdWeather supplies the eBird, Wikipedia and BirdWeather addresses itself, and the integration builds the All About Birds and Macaulay ones. Links open in a new tab and don't expand or close the row.

- **Expanded rows** always show every link that's available.
- **Every row**, without expanding it: turn on `show_ebird`, `show_allaboutbirds`, `show_macaulay` and `show_birdweather` (all off by default).

Wikipedia isn't a button. Tap the description to open the article.

### Confidence, description, activity and behavior

- **Confidence.** A low, medium or high label, from BirdWeather's confidence for the detection. Turn it off with `show_confidence: false`.
- **Description.** A short Wikipedia summary, fetched the first time a row is opened and kept for the rest of the session. Tap it, or "Read more on Wikipedia ›", to open the article. Turn it off with `show_description: false`.
- **Activity chart.** A small chart of the bird's 24-hour activity (▁▂▅█) with its peak hour, from the station's last 7 days. Birds only. Turn it off with `show_activity: false`.
- **Bat behavior.** For a bat, what BirdWeather says it was doing and how sure it is, for example "Search/Clutter · 60%". The bird card shows it under the name.

### Play the call (audio)

When a recording exists, an expanded row shows a **▶ Play call** button, and the bird card shows a play button on the photo. Both play the detection's soundscape in your browser. Hide either with `show_audio: false`. Bats have no play button yet: their recordings are ultrasonic and need processing to be audible.

Audio is off by default. Turn it on in **Settings → Devices & Services → BirdWeather → Configure → Audio**. Unlike the Haikubox integration, this one plays BirdWeather's recording (FLAC) straight from BirdWeather. Nothing is downloaded, processed or saved, and it doesn't need `ffmpeg`.

If your station has audio sharing turned off, its soundscapes are silent. The button still appears but plays nothing, since the integration plays BirdWeather's clip as it is and can't tell that it's silent.

> **No sound in Safari?** Safari's per-site autoplay setting, "Stop Media with Sound", silences the cards. To fix it, go to **Safari → Settings for This Website…** and set Auto-Play to **Allow All Auto-Play**. Chrome, Firefox and the Home Assistant app aren't affected.

---

## Dashboard example

A three-column page using the sections layout:

```yaml
type: sections
title: Bird Details
sections:
  - type: grid
    cards:
      - type: custom:birdweather-bird-list-card
        entity: sensor.backyard_yearly_top_species
        title: Top Species
        top: 20
  - type: grid
    cards:
      - type: custom:birdweather-bird-list-card
        entity: sensor.backyard_daily_top_species
        title: Top species (24 h)
        top: 10
  - type: grid
    cards:
      - type: custom:birdweather-bird-list-card
        entity: sensor.backyard_rarest_species
        title: Rarest species (7 d)
        top: 10
```

---

## Visual editor

You don't have to write YAML. Click **Add card**, pick a BirdWeather card, and set the options in the editor. The entity picker only lists BirdWeather sensors that have a `detections` list. The bird card's editor includes the **Tap action** dropdown and `position`. The list card's editor has the title, how many birds to show, the row size, and the switches for links, confidence, description, activity and audio.

On Home Assistant 2026.6 and later you can also start from a sensor: in **Add to dashboard → By entity**, pick a BirdWeather sensor and the BirdWeather cards that fit it are offered under **Community**. The bird card is offered for every sensor with a `detections` list, and the list card for all of those except `last_bird_detection` and `last_bat_detection`, which hold a single detection.

---

## Theming

The cards use Home Assistant's standard theme variables, so themes and `card_mod` work as usual:

| Variable | Used for |
|--|--|
| `--ha-card-border-radius` | Card and photo corners |
| `--primary-text-color` | Species name |
| `--secondary-text-color` | Scientific name, times, rank |
| `--secondary-background-color` | Photo placeholder and small labels |
| `--divider-color` | Lines between list rows, and the scrollbar |
| `--primary-color` | Buttons, keyboard focus outline, link buttons |
| `--success-color` / `--warning-color` / `--error-color` | The dot on the confidence label (high, medium, low) |
| `--disabled-text-color` | "No data yet" message |

---

## Troubleshooting

### "No recent detections" or a blank card

The card shows the first bird in its sensor's `detections` list. If the list is empty, the card says so instead of showing an old bird.

Why a list might be empty:

- **`last_detection`**: only before the station's very first detection. After that, its saved list keeps it filled.
- **`notable_species`**: nothing heard in 24 hours. That's the intended sign the station has gone quiet.
- **`recent_detections`**: nothing heard in the last hour. Normal at night.

`daily_count` is a number, not a list, so the cards don't accept it.

### Photos show 🐦 instead of the bird

The cards load photos straight from BirdWeather's servers; there's no local copy. The 🐦 placeholder means BirdWeather has no photo for that species yet, or it didn't load. It shows up once a photo is available.

### The card didn't update after an upgrade

Browsers cache the card code. The integration changes the card's URL on every release to get around this, but if the card still looks old, force a refresh (Cmd/Ctrl + Shift + R) in each browser and app you use.

### The editor's entity picker is empty

The picker only shows BirdWeather sensors. If it's empty, check **Settings → Devices & Services** to make sure the BirdWeather integration has been set up.
