# ha-birdweather: to-do and design notes

What's still open, plus the research behind it. Shipped work is in git history and the docs, not here.

## Before 0.7.0

- Version-bump PR: subject `Release 0.7.0: <Name>`, notes in the commit body (`git commit -F`). Lead with the bat-support change to bird counts on bat-edition PUCs.

Known flake: the minimum-HA pytest job occasionally fails at teardown with a "Lingering timer" error, and a re-run clears it (see `docs/contributing.md`). Seen again on #54 in `test_config_flow.py::test_user_flow_shows_form`. If it becomes frequent, find which store schedules a delayed save during the user-flow init and flush or await it in the test.

Decided against (2026-10-02):

- **Serialize stores off the event loop.** The largest store (`species_meta`, about 50 KB) serializes in 0.03 ms. Several stores, the event buffer among them, are changed in place between saves, so doing it safely needs a snapshot at every save site, for no measurable gain. ha-haikubox does it for its daily-count history (up to about 1.8 MB, about 2 ms per save).
- **A logo.** BirdWeather publishes no wordmark; the only logo on its site is the square white bird mark, the same mark as our icon. HA falls back to the icon without a `logo.png`, so shipping that mark changes nothing, and a homemade wordmark would be an unofficial asset for their trademark. Revisit if an official wordmark appears.
- **eco2 sensor.** A survey of 197 public PUCs found 38% reading below the ~420 ppm atmospheric floor (some negative, e.g. -28215 on station 20184). It's an unreliable BSEC estimate, not a per-unit fluke, so clamping can't fix it. Revisit only if BirdWeather's firmware fixes the BSEC eCO2 output.

## Real-time detections (push instead of polling)

Blocked: the `/cable` socket stays silent even when authenticated, so this is a question for BirdWeather.

BirdWeather has a push API that Haikubox doesn't: a GraphQL subscription, `newDetection`, over WebSocket. Their site uses Apollo's `split` link to send subscriptions over WS. It isn't Action Cable (`/cable` 404s).

- Operation: `subscription { newDetection(<filters>) { detection { … } } }`, returning `NewDetectionPayload { detection: Detection! }`, the same `Detection` we already parse.
- Server-side filters, so it isn't a firehose: `stationIds`, `speciesIds`, `classifications`, `confidence/score/probabilityGte/Lte`, `timeOfDayGte/Lte`, `countries`/`continents`, `recordingModes`, `overrideStationFilters`.
- Consume with `gql` (`WebsocketsTransport`) or `websockets` speaking `graphql-ws`: one outbound WS (no inbound port needed), subscribed with `stationIds: [<id>]` and a minimum confidence. On each event, update `last_detection` and fire `new_species` / `unusual_visitor` right away. Keep the 10-minute poll for the aggregate sensors and as the fallback when the socket drops.
- Server-side `confidenceGte` would then filter the live feed upstream instead of in the client.
- Whatever transport we add must restore the last detection on restart (the community relies on MQTT `retain`; we already persist it, so keep that).
- To pin down the transport (the API docs list the operation, not the endpoint, protocol or auth): DevTools → Network → WS on app.birdweather.com (its live map runs this subscription) shows the `wss://` URL, the `Sec-WebSocket-Protocol` (`graphql-transport-ws` or the older `subscriptions-transport-ws`), the `connection_init` payload, and a sample message. Or ask support@birdweather.com.

For the real-time path, this mostly replaces the time-bounded feed item under "Data windows".

## Features not built yet

- **Audio:** cast a call to a `media_player` (a tap action to a speaker); a `media_source` of recent detections; announce a notable or new bird's call; check a rare ID by ear. Stretch: a shareable clip (MP4 with species, confidence and time overlaid, as BirdNET-Go does with ffmpeg).
- **Daily activity:** a dedicated diel heatmap card (`hourly_activity` already feeds any chart card, e.g. apexcharts). For a today-vs-typical view, prefer a `sparkline_window` option (1-day or 7-day) to a second sparkline; 1-day would need a fetch every poll instead of once a day.
- **Regional context:** "rare here but common nearby" (this station's baseline against its neighbors'), a regional rare-bird feed, and diversity or activity percentiles against nearby stations. Needs extra queries against nearby station IDs.
- **History:**
  - first-arrival dates ("spring arrivals") from per-species `dailyDetectionCounts`, better with more than a year of history
  - year over year, which needs at least a year of history (test station 20184 starts 2025-12-25)
  - a seasonality curve, detections by week of year, as its own card or a window toggle rather than another line in the detail view
- **Long-term statistics:** a busy multi-year station could import incrementally with `get_last_statistics` instead of a full re-import each day. The statistics are also left behind when an entry is removed; consider clearing them.
- **PUC hardware:** the OpenWeather-sourced `weather` / `airPollution` blocks (only present when the owner enables `openWeather`, null on 20184, and mostly redundant with HA's weather), spectral light channels, accelerometer/magnetometer, GPS.
- **Blueprints:** build in the community's hard-won notification UX: a cooldown timer, per-person or per-channel targets with their own conditions, custom sounds, and the absence gap in the rare-return message (`unusual_visitor` already carries `days_absent`). Add a "quiet period" alert for short silences that stays quiet at night and in winter, a softer companion to `extended_silence`.
- **Feeder-camera correlation** (stretch): pair an audio detection with a Frigate / WhosAtMyFeeder snapshot taken at the same time, "heard and saw it".

## Data windows

- `DETECTION_FETCH_LIMIT` (300 recent events) can fall short of 24 hours on a busy station. The 24-hour count, top species and diversity already come from BirdWeather's own totals, but the `detections_24h` list still feeds the 7-day rarest list, notability and the recent and last-detection records. Switching the feed to a time-bounded query (`from`/`period` plus cursor paging) would give a true 24-hour list.
- Day boundaries are UTC, inherited from Haikubox. For a station in a fixed place, keying the 7-day store and daily windows to the station's time zone is arguably more correct.
- The rarity baseline defaults to 1 month (`RARITY_PERIOD_MONTHS`, now an option from 1 to 24 months). Many species fall outside a month and cap at rarity 1.0, so a longer default may be better.

## Reference links and photos

- **Photo credits.** Some images come with no credit or license, so no caption is shown; a generic "Photo: BirdWeather" line could stand in. `imageCredit` is sometimes a bare URL rather than a name; left as is.

## Cards

- **The detail view is getting crowded.** The list card's expanded row now has eBird, All About Birds, Macaulay and BirdWeather links, the confidence label, the alpha code, the Wikipedia description, the activity chart and the photo credit, each behind its own toggle. Consider grouping them (a compact and a full detail mode, or folding the secondary details away) before adding more. A new per-species detail should reuse something already there, such as a window toggle on the activity chart, rather than add a line.

## Known limitations (BirdWeather's, not fixable here)

- **Tightly cropped species photos.** BirdWeather serves one 400×400 square crop per species (a contributor or Wikimedia image), and some are cropped tightly enough to clip the bird. The cards use `object-fit: contain` with a blur fill, so they show the whole file and never crop further, but they can't recover pixels BirdWeather already cut, and the `standard` and `thumbnail` sizes share the same crop. It's documented in `docs/troubleshooting.md`. Getting the full image elsewhere (Wikimedia or eBird) is the only workaround, and not worth the licensing and complexity for the occasional bad crop. Clipped species worth reporting to BirdWeather:
  - **Painted Bunting** (`Passerina ciris`, species 2376): beak clipped at the right edge (photo by Doug Janson, CC BY-SA 3.0).
