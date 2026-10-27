#!/usr/bin/env bash
# Render every scene and stitch them into one video: counters_video.mp4
# Usage: ./render.sh [quality flag, default -qh]   (needs manim + ffmpeg, no LaTeX)
set -euo pipefail
cd "$(dirname "$0")"
Q="${1:--qh}"
MEDIA="${MEDIA_DIR:-media}"
manim "$Q" --media_dir "$MEDIA" counters.py -a
case "$Q" in
  -ql) RES=480p15 ;; -qm) RES=720p30 ;; -qh) RES=1080p60 ;; -qp) RES=1440p60 ;; -qk) RES=2160p60 ;;
  *) echo "unknown quality flag $Q" >&2; exit 1 ;;
esac
DIR="$MEDIA/videos/counters/$RES"
LIST=$(mktemp)
for s in $(grep -oE 'S[0-9]{2}_[A-Za-z0-9]+' <(grep -A2 '^SCENE_ORDER' counters.py)); do
  echo "file '$(cd "$DIR" && pwd)/$s.mp4'" >> "$LIST"
done
ffmpeg -loglevel error -y -f concat -safe 0 -i "$LIST" -c copy counters_video.mp4
rm -f "$LIST"
echo "Wrote $(pwd)/counters_video.mp4"
