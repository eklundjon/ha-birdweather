# Automations

The integration fires Home Assistant events for noteworthy detections, exposes
them as **device triggers** in the automation editor, and ships four ready-made
**blueprints** that turn them into push notifications or media playback.

## Device triggers (the easy path)

Every BirdWeather device offers these triggers under **Settings → Automations →
Create → When → Device**:

| Trigger | Fires when |
| --- | --- |
| **New species detected** | A species is heard at this station for the **first time ever** — a genuine lifetime first. |
| **Unusual visitor detected** | A species the station already knows **returns after a long absence** (default 30 days unheard; see [Tuning](#tuning-the-unusual-visitor-threshold)). |
| **Watched species detected** | A species **you chose to watch** is heard. Pick the species in **Settings → Devices & Services → BirdWeather → Configure** (a list of ones your station has detected, plus a free-text box for ones it hasn't yet). |

Pick the station, pick the trigger, and add whatever actions you like. The
trigger makes the detection's details available to your actions through the
event data described below.

## Blueprints (push notification in two clicks)

Four blueprints ship as starting points — three mobile notifications (one per
device trigger) plus a media-player one:

- **BirdWeather — New species notification** (`new_species`) — push with the
  bird's photo, the running lifetime species count, and tap-through **action
  buttons** to eBird and Wikipedia.
- **BirdWeather — Unusual visitor notification** (`unusual_visitor`) — push that
  **attaches the call recording** when audio is enabled and the detection has a
  soundscape, falling back to the photo otherwise.
- **BirdWeather — Watched species notification** (`watched_species`) — push with
  the bird's photo for the species you've chosen in the integration's options.
- **BirdWeather — Play the call on a media player** — plays the detection's
  recording on a speaker/display; its trigger type is selectable.

Each asks which **BirdWeather station** to watch and either a **mobile-app
device** to notify or a **media player** to play on; titles/messages are
editable.

These deliberately show off **different event features** — photo, action buttons
(`ebird_url`/`wikipedia_url`), `lifetime_species_count`, and audio
(`audio_url`). None are tied to a particular trigger: **every `birdweather_event`
carries the same fields** (see the table below), so you can mix and match — e.g.
add eBird buttons to the unusual-visitor push, or play the call on a new species.

> **Audio caveats.** `audio_url` is BirdWeather's soundscape clip (FLAC). It's
> only present when audio is enabled in the options *and* the station has a
> recording for the detection (a station with audio sharing off produces silent
> clips). FLAC may not play in iOS notification attachments or on every media
> player.

### Importing a blueprint

In Home Assistant, go to **Settings → Automations & scenes → Blueprints →
Import blueprint** and paste the raw URL:

```
https://github.com/eklundjon/ha-birdweather/blob/main/blueprints/automation/birdweather/new_species_notification.yaml
https://github.com/eklundjon/ha-birdweather/blob/main/blueprints/automation/birdweather/unusual_visitor_notification.yaml
https://github.com/eklundjon/ha-birdweather/blob/main/blueprints/automation/birdweather/watched_species_notification.yaml
https://github.com/eklundjon/ha-birdweather/blob/main/blueprints/automation/birdweather/play_call_on_media_player.yaml
```

Then **Settings → Automations & scenes → Create automation → Use blueprint**,
choose the imported blueprint, and fill in the station and the device to notify.

> The bird photo is attached as the notification image. On Android it shows
> inline; on iOS it appears when you long-press / expand the notification.

## Event reference

All three triggers are filtered views of a single bus event,
`birdweather_event`, discriminated by its `type` field. You can also trigger on
the raw event (**When → Other → Manual event**, event type `birdweather_event`)
to react to several stations at once or match on the payload yourself.

Event data:

| Field | Description |
| --- | --- |
| `type` | `new_species`, `unusual_visitor`, or `watched_species`. |
| `device_id` | HA device-registry id of the station (what the device trigger filters on). |
| `station_id` | The BirdWeather station ID. |
| `device_name` | Friendly name of the station. |
| `species` | Bird common name. |
| `scientific_name` | Scientific name. |
| `sp_code` | eBird species code. |
| `alpha` | Four-letter alpha banding code (may be absent). |
| `image_url` | Photo URL for the species (may be absent). |
| `audio_url` | BirdWeather soundscape clip (FLAC) for the detection, or `null` when audio is disabled or no recording exists. |
| `confidence` | Detection confidence (0–1). |
| `confidence_band` | `low` / `medium` / `high`. |
| `last_seen` | Timestamp of this detection. |
| `count` | Times this species was heard in the recent (1-hour) window. |
| `ebird_url` | eBird species page. |
| `wikipedia_url` | Wikipedia article. |
| `allaboutbirds_url` | All About Birds species guide. |
| `macaulay_url` | Macaulay Library media page. |
| `birdweather_url` | BirdWeather species page. |
| `rarity_score` | Rarity vs. the station's rarity baseline (1.0 = rarest). |
| `yearly_rank` | Rank within the rarity baseline (1 = most common). The field name mirrors the Haikubox pipeline and is kept for compatibility. |
| `days_absent` | **`unusual_visitor` only** — days since the previous sighting. |
| `lifetime_species_count` | **`new_species` only** — total distinct species ever detected at this station, including this one. |

In templates these are reached via `trigger.event.data.<field>` (for example
`{{ trigger.event.data.species }}`).

## Tuning the unusual-visitor threshold

`unusual_visitor` fires when a known species reappears after at least *N* days
unheard. *N* defaults to **30 days** and is set per-station in **Settings →
Devices & Services → BirdWeather → Configure → "Unusual visitor: days
unheard."**

The threshold is built on the integration's persisted last-seen history, so it
measures the real gap since the species was last heard — independent of the
rarity baseline, which makes it a more reliable alerting signal than raw rarity.

## Confidence-gating alerts

A separate **"Only alert above confidence"** option suppresses all three
triggers for detections below a chosen confidence, independent of the feed
filter that hides low-confidence detections from the sensors. So you can keep
seeing "maybe" detections on the cards while only being pinged on confident
hits. See [sensors.md](sensors.md#confidence).

## How the events stay quiet

The events are designed not to flood you:

- **Fresh installs are silent.** Setup pre-seeds the station's species history
  from the first 24-hour window, so bootstrapping doesn't fire a burst of
  `new_species` events for birds the station already knew about.
- **Restarts are silent for `unusual_visitor`/`watched_species`.** The first
  poll of each session only establishes a baseline; it won't replay every
  long-absent or watched bird already in the current window.
- **No re-firing while a bird lingers.** A species that stays present across
  several polls fires once, not on every poll, because the events trigger on the
  *edge* of a species entering the recent window.
