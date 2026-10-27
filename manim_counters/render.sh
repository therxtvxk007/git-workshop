#!/usr/bin/env bash
# Render every scene and stitch them into one video: counters_video.mp4
# Usage: ./render.sh [quality flag, default -qh]   (needs manim + ffmpeg, no LaTeX)
set -euo pipefail
cd "$(dirname "$0")"
Q="${1:--qh}"
MEDIA="${MEDIA_DIR:-media}"
manim "$Q" --media_dir "$MEDIA" counters.py -a
DIR=$(dirname "$(find "$MEDIA/videos/counters" -name S01_Intro.mp4 | head -1)")
LIST=$(mktemp)
for s in $(python3 -c "import ast,sys;t=ast.parse(open('counters.py').read());print(' '.join(next(ast.literal_eval(n.value) for n in t.body if isinstance(n,ast.Assign) and n.targets[0].id=='SCENE_ORDER')))"); do
  echo "file '$PWD/$DIR/$s.mp4'" >> "$LIST"
done
ffmpeg -loglevel error -y -f concat -safe 0 -i "$LIST" -c copy counters_video.mp4
rm -f "$LIST"
echo "Wrote $(pwd)/counters_video.mp4"
