DOMAIN = "birdweather"

# A BirdWeather station is identified by its public station ID (chosen during
# onboarding via nearby-station discovery). Unlike Haikubox there is no token
# for public stations — the GraphQL API serves their data anonymously.
CONF_STATION_ID = "station_id"
CONF_STATION_NAME = "station_name"

# Onboarding discovery radius (km) around HA's configured location.
CONF_RADIUS_KM = "radius_km"
DEFAULT_RADIUS_KM = 25

# Public GraphQL endpoint (see client.py). No auth for public stations.
API_URL = "https://app.birdweather.com/graphql"

# How often to poll (seconds).
DEFAULT_SCAN_INTERVAL = 600  # 10 minutes

# Sliding windows, mirroring the Haikubox pipeline: the recent (1h) view is
# derived client-side from the 24h pull; "daily" sensors use the trailing 24h.
RECENT_WINDOW_HOURS = 1
DAILY_WINDOW_HOURS = 24

# How many recent detection events to pull per poll. BirdWeather's
# detections(first:) returns newest-first; this is the ceiling we filter the
# 1h/24h windows out of. Busy stations may need a time-bounded query later.
DETECTION_FETCH_LIMIT = 300

# Soft caps on the per-sensor list attributes (same rationale as Haikubox:
# bound state-attribute size). Per-event vs per-species as in haikubox.
LAST_DETECTION_EVENT_LIMIT = 50
NEW_SPECIES_HISTORY_LIMIT = 50

# Notability tuning (identical model to Haikubox): notability_score =
# w*rarity + (1-w)*recency over a 24h linear-decay window; w is the
# user-facing "% weight toward rarity".
CONF_NOTABLE_RARITY_WEIGHT = "notable_rarity_weight"
DEFAULT_NOTABLE_RARITY_WEIGHT = 70  # percent
NOTABILITY_WINDOW_HOURS = 24

# Rarity baseline: BirdWeather's per-station topSpecies counts over a trailing
# period stand in for Haikubox's yearly-count endpoint. Default 1 month — a
# fixed-location station's recent frequency is a better "what's normal here"
# signal than a calendar-year tally, and sidesteps the year-reset problem.
RARITY_PERIOD_MONTHS = 1

# Activity / diversity / new-species windows. BirdWeather serves true per-period
# counts natively, so these are computed from the API directly (no local per-day
# store or backfill — unlike Haikubox, whose REST surface forced that).
ACTIVITY_BASELINE_DAYS = 30  # "typical day" = trailing-window total / this
NEW_SPECIES_WINDOW_DAYS = 30  # species first heard within this many days = "new"

# Automation events — one bus event, type-discriminated, mirroring haikubox.
EVENT_BIRDWEATHER = "birdweather_event"
TRIGGER_NEW_SPECIES = "new_species"
TRIGGER_UNUSUAL_VISITOR = "unusual_visitor"
TRIGGER_WATCHED_SPECIES = "watched_species"  # a user-chosen species was detected
TRIGGER_TYPES = (TRIGGER_NEW_SPECIES, TRIGGER_UNUSUAL_VISITOR, TRIGGER_WATCHED_SPECIES)

# unusual_visitor: known species reappearing after >= this many days unheard.
CONF_ABSENCE_DAYS = "absence_days"
DEFAULT_ABSENCE_DAYS = 30

# watched_species: fire the watched_species trigger when one of these is heard.
# Two options-flow inputs combine into the watch set: a multi-select picked from
# species the station has already detected, plus a free-text list (one common
# name per line) for species not yet seen here (the aspirational case).
CONF_WATCHED_SPECIES = "watched_species"       # list[str] from the pick-list
CONF_WATCHED_EXTRA = "watched_species_extra"   # newline-separated free text
