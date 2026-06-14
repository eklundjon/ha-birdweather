#!/usr/bin/env bash
#
# sync-cards.sh — regenerate the BirdWeather Lovelace cards from the (canonical,
# more complete) Haikubox cards by brand substitution + a FEATURES flip.
#
# The two integrations deliberately keep DISTINCT branded element names
# (`haikubox-bird-card` vs `birdweather-bird-card`, etc.) so that when both
# are installed there is no shared global custom-element name — and therefore
# no first-define-wins race if the two are on different versions. The card
# *bodies* are otherwise identical generic logic (they read only the common
# `detections[]` sensor contract), so the BirdWeather variants are produced by
# substituting the brand tokens plus flipping the FEATURES flags:
#
#     Haikubox -> BirdWeather      (class names, customCards labels, comments)
#     haikubox -> birdweather      (element tags, platform filter, popup ids)
#     FEATURES { …: false }        -> true  (BirdWeather supplies that data)
#
# Source path defaults to a sibling ha-haikubox checkout; override with $1.
#
# STATUS (re-converged 2026-06-14): the earlier fork is HEALED. Haikubox has
# since absorbed both fork reasons — photo attribution and blur-fill image
# handling are now in the canonical Haikubox cards (carried for everyone,
# null-guarded, gated by the FEATURES object) — and Haikubox additionally gained
# the single-bird detail popup (the ⓘ button). So Haikubox is once again the
# canonical card and BirdWeather is regenerated from it.
#
# After running, RE-APPLY the two by-hand bits this sync does NOT carry:
#   1. The file header comments (each card's top-of-file block).
#   2. The BirdWeather reference link on the details card (`birdweather_url`),
#      which the canonical Haikubox card intentionally omits — grep the live
#      card for `bw:` / `birdweather_url` / `bwField` to see the four spots.

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

  # Brand tokens + the FEATURES flip (each card matches only its own flag line).
  sed -e 's/Haikubox/BirdWeather/g' \
      -e 's/haikubox/birdweather/g' \
      -e 's/const FEATURES = { confidence: false, attribution: false };/const FEATURES = { confidence: true, attribution: true };/' \
      -e 's/const FEATURES = { confidence: false, activity: false };/const FEATURES = { confidence: true, activity: true };/' \
      "$src" > "$dst"
  echo "wrote $dst"
done

echo
echo "NOW re-apply by hand (not carried by this sync):"
echo "  - the top-of-file header comment in each card"
echo "  - the BirdWeather reference link on the details card (grep: bw: / birdweather_url / bwField)"
