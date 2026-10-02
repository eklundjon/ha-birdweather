# Automations

The integration fires a Home Assistant event when it hears something worth knowing about, offers those events as device triggers in the automation editor, and comes with four blueprints that turn them into phone notifications or play the call on a speaker.

## Device triggers

Every BirdWeather device offers these triggers under **Settings → Automations → Create → When → Device**:

| Trigger | Fires when |
| --- | --- |
| **New species detected** | A species is heard at this station for the first time ever. |
| **Unusual visitor detected** | A species the station already knows comes back after a long absence: 30 days unheard by default (see [the threshold](#tuning-the-unusual-visitor-threshold)). |
| **Bat activity started** | Only with [bat support](bats.md) on. Bats are heard after at least 60 minutes without one. |
| **Watched species detected** | A species you chose to watch is heard. Pick the species in **Settings → Devices & Services → BirdWeather → Configure**, from a list of ones your station has heard, or in a free-text box for ones it hasn't yet. |

Pick the station and the trigger, then add whatever actions you like. Your actions can use the detection's details from the event data described [below](#event-reference).

## Blueprints

There are four blueprints to start from, three phone notifications (one for each device trigger) and one for a speaker:

- **BirdWeather: New species notification** (`new_species`). A notification with the bird's photo, the station's lifetime species count, and buttons that open eBird and Wikipedia.
- **BirdWeather: Unusual visitor notification** (`unusual_visitor`). A notification that attaches the recording when audio is turned on and the detection has a soundscape, and the photo otherwise.
- **BirdWeather: Watched species notification** (`watched_species`). A notification with the bird's photo, for the species you've chosen in the integration's options.
- **BirdWeather: Play the call on a media player.** Plays the detection's recording on a speaker or display. You choose which trigger starts it.

Each asks which BirdWeather station to use, and either a phone (a mobile-app device) to notify or a media player to play on. The titles and messages can be changed.

Each one shows off a different part of the event: the photo, the eBird and Wikipedia buttons (`ebird_url` and `wikipedia_url`), `lifetime_species_count`, and the recording (`audio_url`). None of that is tied to a particular trigger. Every `birdweather_event` carries the same fields (see the table below), so you can mix and match: add the eBird button to the unusual-visitor notification, or play the call for a new species.

*Note:* `audio_url` is BirdWeather's soundscape clip (FLAC). It's only there when audio is turned on in the options and the station has a recording for that detection, and a station with audio sharing off produces silent clips. FLAC may not play in iOS notification attachments or on every media player.

### Importing a blueprint

Home Assistant doesn't install blueprints with an integration. It imports them from a URL, one at a time. Click a badge to open the import dialog with the blueprint filled in:

| Blueprint | Import |
| --- | --- |
| BirdWeather: New species notification | [![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Feklundjon%2Fha-birdweather%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fbirdweather%2Fnew_species_notification.yaml) |
| BirdWeather: Unusual visitor notification | [![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Feklundjon%2Fha-birdweather%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fbirdweather%2Funusual_visitor_notification.yaml) |
| BirdWeather: Watched species notification | [![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Feklundjon%2Fha-birdweather%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fbirdweather%2Fwatched_species_notification.yaml) |
| BirdWeather: Play the call on a media player | [![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Feklundjon%2Fha-birdweather%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fbirdweather%2Fplay_call_on_media_player.yaml) |

To do it by hand, go to **Settings → Automations & scenes → Blueprints → Import blueprint** and paste the blueprint's URL:

```
https://github.com/eklundjon/ha-birdweather/blob/main/blueprints/automation/birdweather/new_species_notification.yaml
https://github.com/eklundjon/ha-birdweather/blob/main/blueprints/automation/birdweather/unusual_visitor_notification.yaml
https://github.com/eklundjon/ha-birdweather/blob/main/blueprints/automation/birdweather/watched_species_notification.yaml
https://github.com/eklundjon/ha-birdweather/blob/main/blueprints/automation/birdweather/play_call_on_media_player.yaml
```

Then go to **Settings → Automations & scenes → Create automation → Use blueprint**, choose the blueprint you imported, and fill in the station and the device to notify.

The bird's photo is attached to the notification as its image. On Android it shows in the notification. On iOS it appears when you long-press or expand the notification.

## Event reference

All the device triggers are filters on one event, `birdweather_event`, which says what happened in its `type` field. You can also trigger on the event directly (**When → Other → Manual event**, event type `birdweather_event`), for example to cover several stations in one automation, or to match on other fields yourself.

The event data:

| Field | Description |
| --- | --- |
| `type` | `new_species`, `unusual_visitor`, `watched_species` or `bat_activity` |
| `classification` | `bird` or `bat`. Bats only appear with [bat support](bats.md) on. |
| `device_id` | The station's device ID in Home Assistant (what the device trigger filters on) |
| `station_id` | The BirdWeather station ID |
| `device_name` | The station's name |
| `species` | Common name |
| `scientific_name` | Scientific name |
| `sp_code` | eBird species code |
| `alpha` | Four-letter alpha banding code. May be missing. |
| `image_url` | Photo URL for the species. May be missing. |
| `audio_url` | BirdWeather's soundscape clip (FLAC) for the detection, or `null` when audio is off or there's no recording |
| `confidence` | The detection's confidence, from 0 to 1 |
| `confidence_band` | `low`, `medium` or `high` |
| `last_seen` | When this detection happened |
| `count` | How many times this species was heard in the recent window (1 hour). For `bat_activity`, how many bat detections there have been since the previous one. |
| `ebird_url` | eBird species page |
| `wikipedia_url` | Wikipedia article |
| `allaboutbirds_url` | All About Birds species guide |
| `macaulay_url` | Macaulay Library media page |
| `birdweather_url` | BirdWeather species page |
| `rarity_score` | How rare the species is compared with the station's rarity baseline (1.0 is the rarest) |
| `yearly_rank` | Rank in the rarity baseline (1 is the most common). The name comes from the Haikubox integration and is kept for compatibility. |
| `days_absent` | `unusual_visitor` only. Days since the species was last heard. |
| `lifetime_species_count` | `new_species` only. How many different species the station has ever heard, including this one. For a bat, how many bat species. |
| `behavior`, `behavior_code`, `behavior_confidence` | Bats only. What BirdWeather says the bat was doing (for example "Search/Clutter", `bat_search_clutter`) and how sure it is. `null` for birds. |
| `quiet_minutes` | `bat_activity` only. Minutes since the previous bat. |

In templates, these are `trigger.event.data.<field>`, for example `{{ trigger.event.data.species }}`.

## Tuning the unusual-visitor threshold

`unusual_visitor` fires when a species the station knows comes back after at least *N* days unheard. *N* is 30 days by default, and you can change it for each station in **Settings → Devices & Services → BirdWeather → Configure → Unusual visitor: days unheard**.

It's based on the integration's saved record of when each species was last heard, so it measures the real gap since the bird was last heard. That doesn't depend on the rarity baseline, which makes it more reliable for alerts than rarity on its own.

## Only alerting on confident detections

A separate option, **Only alert above confidence**, stops the triggers from firing for detections below a confidence you choose. It's independent of the filter that hides low-confidence detections from the sensors, so you can keep seeing "maybe" detections on the cards while only getting notified about confident ones. See [sensors.md](sensors.md#confidence).

## How the events stay quiet

The events are designed not to flood you:

- **A new install is silent.** Setup fills in the station's species history from the first 24 hours of detections, so getting started doesn't send a burst of `new_species` events for birds the station already knew.
- **Restarts are silent for `unusual_visitor` and `watched_species`.** The first poll after a restart only records what's currently around. It won't fire for every long-absent or watched bird already in the window.
- **A bird that hangs around fires once.** A species heard across several polls fires on the poll where it first shows up in the recent window, not on every poll.
