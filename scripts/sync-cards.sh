#!/usr/bin/env bash
#
# sync-cards.sh — regenerate the BirdWeather Lovelace cards from the (more
# mature) Haikubox cards by brand substitution.
#
# The two integrations deliberately keep DISTINCT branded element names
# (`haikubox-bird-card` vs `birdweather-bird-card`, etc.) so that when both
# are installed there is no shared global custom-element name — and therefore
# no first-define-wins race if the two are on different versions. The card
# *bodies* are otherwise identical generic logic (they read only the common
# `detections[]` sensor contract), so the BirdWeather variants are produced by
# substituting the brand tokens:
#
#     Haikubox -> BirdWeather      (class names, customCards labels, comments)
#     haikubox -> birdweather      (element tags, platform filter, popup ids)
#
# Source path defaults to a sibling ha-haikubox checkout; override with $1.
#
# STATUS (forked 2026-06-04): the cards have now FORKED. BirdWeather has card
# features Haikubox lacks — photo attribution (BirdWeather supplies
# imageCredit/License; Haikubox doesn't) and blur-fill image handling (its
# photos are 1:1 squares vs Haikubox's 4:3). This script therefore captured only
# the ONE-TIME seeding and must NOT be re-run over the live cards — it would
# silently drop those BirdWeather-only changes. Kept for reference / to
# re-derive a fresh starting point. The BirdWeather cards are now hand-maintained.

set -euo pipefail

SRC="${1:-../ha-haikubox/custom_components/haikubox/www}"
DST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/custom_components/birdweather/www"

declare -a MAP=(
  "haikubox-bird-card.js:birdweather-bird-card.js"
  "haikubox-details-card.js:birdweather-details-card.js"
)

mkdir -p "$DST"

for pair in "${MAP[@]}"; do
  src_name="${pair%%:*}"
  dst_name="${pair##*:}"
  src="$SRC/$src_name"
  dst="$DST/$dst_name"
  [ -f "$src" ] || { echo "ERROR: source not found: $src" >&2; exit 1; }

  {
    echo "// GENERATED from ha-haikubox/$src_name by scripts/sync-cards.sh — do not edit directly."
    sed -e 's/Haikubox/BirdWeather/g' -e 's/haikubox/birdweather/g' "$src"
  } > "$dst"
  echo "wrote $dst"
done
