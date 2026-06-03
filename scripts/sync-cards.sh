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
# NOTE: the generated files are derived artifacts — edit the Haikubox cards
# (or this script) and re-run, rather than hand-editing the output. Once
# BirdWeather grows brand-only card features (audio playback, confidence),
# revisit whether to keep pure generation or fork.

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
