#!/usr/bin/env bash
# Render every lesson and copy the finished videos into ./videos.
# Usage: ./render.sh [manim quality flag, default -qh]
set -euo pipefail
cd "$(dirname "$0")"

quality="${1:--qh}"
scenes=(
  "national_income NationalIncome"
  "inflation Inflation"
  "value_engineering ValueEngineering"
  "capital_budgeting CapitalBudgeting"
)

mkdir -p videos
for entry in "${scenes[@]}"; do
  read -r file scene <<<"$entry"
  manim "$quality" --media_dir media "$file.py" "$scene"
  find "media/videos/$file" -name "$scene.mp4" -not -path "*partial*" \
    -exec cp {} "videos/$file.mp4" \;
done
echo "Done: $(ls videos)"
