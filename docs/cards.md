# Custom cards

The integration registers two custom Lovelace cards automatically — no manual resource configuration required.

- [`birdweather-bird-card`](#birdweather-bird-card) — single bird, photo + species + relative timestamp
- [`birdweather-bird-list-card`](#birdweather-bird-list-card) — ranked list with tap-to-expand detail rows
- [Dashboard example](#dashboard-example)
- [Visual editor](#visual-editor)
- [Theming](#theming)
- [Troubleshooting](#troubleshooting)

Both cards work on **Home Assistant 2025.4+** (the integration's minimum). They share their render logic with the sibling Haikubox cards — they're generated from the canonical Haikubox cards by `scripts/sync-cards.sh`, with BirdWeather's reference link layered back on (see [contributing.md](contributing.md)).

---

## `birdweather-bird-card`

Displays a single bird detection with a photo, species name, scientific name, and a relative timestamp.

```yaml
type: custom:birdweather-bird-card
entity: sensor.backyard_notable_species
grid_options:
  columns: 6
  rows: 4
```

The card is fully responsive to width and height: in portrait the photo fills the card width over an edge-to-edge blurred fill (BirdWeather photos are 1:1 squares), with text centred below; when wider than ~3:2 the photo moves left and text appears on the right. Text scales with the card via container-query units. Two round overlay buttons sit at the **top** corners (clear of the bottom photo-credit strip): **▶ play** (top-left, when audio is enabled and a recording exists) and **ⓘ details** (top-right) — see below.

Works with any **list-bearing** sensor — the 8 that expose a per-species `detections` list (`recent_detections`, `last_detection`, `daily_top_species`, `notable_species`, `new_species`, `yearly_top_species`, `rarest_species`, `watched_species`). The numeric/diagnostic sensors (`daily_count`, `lifetime_species`, `species_diversity`, `activity_level`, `new_species_window`, `history_start`, `peak_activity_hour`) have no list and aren't offered. By default the card renders the **top-ranked** record. Empty list → "No recent detections."

The relative timestamp refreshes every 60 seconds independently of the poll cadence, so it stays honest between polls.

### Showing a different rank (`position`)

Set `position` (1-based) to show a rank other than the top — handy for a column of single-bird cards each surfacing a different rank from the same sensor:

```yaml
- type: custom:birdweather-bird-card
  entity: sensor.backyard_daily_top_species
  position: 1
- type: custom:birdweather-bird-card
  entity: sensor.backyard_daily_top_species
  position: 2
```

If `position` exceeds the list length, the card shows its empty state.

### The details (ⓘ) button

The ⓘ button at the top-right opens a popup with this bird's **full detail view** — the list card's detail render (large photo, Wikipedia description, confidence, activity sparkline, reference links, play button). Toggle it with `show_details` (default on). The popup has a backdrop and closes on click-outside or **Esc**.

### Per-event vs. per-species

Most sensors' `detections` lists are per-species. `last_detection.detections` is the exception — per-event, from a persisted rolling cache, so the card pointed at it shows the single most recent event and keeps showing it through restarts and outages (#62). The "station has gone silent" signal is **`notable_species` going `unknown`** or **`recent_detections` reading 0**, not `last_detection` blanking. See [sensors.md](sensors.md#per-species-vs-per-event-live-vs-persisted).

### Tap action

Supported actions: `more-info` (**default**), `show-list` (popup of the full species list for this sensor), `navigate`, `url`, and `none`. `navigation_path` / `url_path` accept tokens substituted from the displayed record:

| Token | Substituted with |
|--|--|
| `{species}` | Common name (e.g. `Downy Woodpecker`) |
| `{species_slug}` | Common name, spaces → underscores (`Downy_Woodpecker`) |
| `{sp_code}` | eBird species code (e.g. `dowwoo`) |
| `{scientific_name}` | Latin binomial |

```yaml
# Open the eBird page for the bird currently displayed.
type: custom:birdweather-bird-card
entity: sensor.backyard_last_detection
tap_action:
  action: url
  url_path: https://ebird.org/species/{sp_code}
```

`action: show-list` opens a modal popup containing the [`birdweather-bird-list-card`](#birdweather-bird-list-card) for the **same sensor**. The visual editor exposes a **Tap action** dropdown (More info / Show species list / Navigate / Open URL / None) plus a path field.

---

## `birdweather-bird-list-card`

A ranked species list with tap-to-expand detail rows. Works with **any** list-bearing sensor — they share the same [`detections` contract](sensors.md#the-detections-contract).

```yaml
type: custom:birdweather-bird-list-card
entity: sensor.backyard_yearly_top_species
title: Top Species               # optional; blank → entity friendly name
top: 10                          # max items (default: 10)
row_size: small                 # small | medium | large (default: small)
show_ebird: false               # eBird links in compact view (default: false)
show_allaboutbirds: false       # All About Birds links in compact view (default: false)
show_macaulay: false            # Macaulay Library links in compact view (default: false)
show_birdweather: false         # BirdWeather links in compact view (default: false)
show_confidence: true           # confidence chip in the detail view (default: true)
show_description: true          # Wikipedia description in the detail view (default: true)
show_activity: true             # diel activity sparkline in the detail view (default: true)
show_audio: true                # "Play call" button in the detail view (default: true)
grid_options:
  columns: 12
  rows: 4
```

Each row shows the species, its `#rank`, photo, and scientific name. **Tap a row** to expand it in place — a larger photo, the scientific name, a Wikipedia description (tap to open the article), `count×` and a "last heard" time where available, a **confidence** chip (low/medium/high), a **diel activity sparkline** ("most active ~7h"), a play button, and reference links. Tap again to collapse; only one row is open at a time.

### Row size

`row_size` scales the compact rows — `small` (default), `medium`, or `large` grow the thumbnail, padding, and text together. Also a dropdown in the editor.

### Reference link buttons

Each row can link out to **eBird**, **All About Birds**, **Macaulay Library**, and **BirdWeather**. The integration surfaces the URLs (BirdWeather supplies authoritative eBird/Wikipedia/BirdWeather URLs; All About Birds and Macaulay are templated); the card renders them. They open in a new tab and don't toggle the row.

- **Detail view — always shown.** All available links appear when a row is expanded.
- **Compact row — opt-in.** `show_ebird`, `show_allaboutbirds`, `show_macaulay`, `show_birdweather` (default `false`) add buttons to the always-visible compact row. (**Wikipedia** isn't a button — it's reached by tapping the description blurb.)

### Confidence, description, and activity

- **Confidence** — a low/medium/high chip in the detail view (`show_confidence`, default on), derived from BirdWeather's per-detection confidence.
- **Description** — a short **Wikipedia** summary, fetched on demand the first time a row is opened and cached for the session (`show_description`, default on). Tap it or the "Read more on Wikipedia ›" cue to open the article.
- **Activity sparkline** — a 24-hour diel curve (▁▂▅█) with the peak hour, from the station's trailing-7-day time-of-day data (`show_activity`, default on).

### Play the call (audio)

When a row has a recording, the detail view shows a **▶ Play call** button (and the bird card a round play button) that plays the detection's soundscape in the browser. Toggle with `show_audio` (default on, both cards).

**Audio is off by default** — enable it at **Settings → Devices & Services → BirdWeather → Configure → Audio**. Unlike the sibling Haikubox integration, BirdWeather audio is **streamed directly** from BirdWeather's soundscape URL (FLAC) — nothing is downloaded, normalized, or cached locally, and no `ffmpeg` is needed.

> If your BirdWeather station has audio sharing turned **off**, its soundscapes are silent — the button appears but plays nothing (the integration streams BirdWeather's clip and can't detect a silent one).

> **No sound in Safari?** Safari's per-site **Auto-Play: "Stop Media with Sound"** silences in-browser playback. Fix it at Safari → Settings for This Website… → **Allow All Auto-Play**. Chrome, Firefox, and the HA app are unaffected.

---

## Dashboard example

A three-column details view using the sections layout:

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

Both cards have a visual editor the dashboard exposes automatically. The entity picker is **pre-filtered to BirdWeather sensors that expose a `detections` list**, so only the 8 list-bearing sensors are offered. The single-bird card's editor also includes the **Tap action** picker and `position`; the list card's editor exposes the title, max items, row size, and the link/confidence/description/activity/audio toggles.

---

## Theming

Both cards consume Home Assistant's standard CSS variables, so themes and `card_mod` work transparently:

| Variable | Used for |
|--|--|
| `--ha-card-border-radius` | Image and card corner radius |
| `--primary-text-color` | Species name |
| `--secondary-text-color` | Scientific name, timestamps, rank |
| `--secondary-background-color` | Image placeholder, metric chips |
| `--divider-color` | Row separators; default scrollbar |
| `--primary-color` | Buttons, focus outline, link buttons |
| `--success-color` / `--warning-color` / `--error-color` | Confidence chip dot (high/medium/low) |
| `--disabled-text-color` | Empty-state text |

---

## Troubleshooting

### "No recent detections" / blank card

The card renders `detections[0]` from its bound entity. If the list is empty it shows the empty state rather than a stale value. By sensor: `last_detection` only blanks before the station's very first detection (its cache persists otherwise); `notable_species` is `unknown` when nothing's been heard in 24 h (the intended silence signal); `recent_detections` is empty during quiet hours. `daily_count` is numeric, not a list, so the cards don't accept it.

### Images show the placeholder

BirdWeather serves photos from its own CDN; the cards load those URLs directly (there's no local image cache). A 🐦 placeholder means BirdWeather has no image for that species yet or the URL failed to load — it resolves once a photo is available.

### Card hasn't picked up the latest version after upgrade

Card JS is browser-cached. The integration appends a `?v=<version>` bust on upgrade; if you still see old behaviour, hard-refresh the dashboard tab (Cmd/Ctrl + Shift + R), and refresh each dashboard/app.

### Editor entity picker is empty

The picker is filtered to BirdWeather entities. If none show up, the integration probably hasn't set up an entry yet — check **Settings → Devices & Services**.
