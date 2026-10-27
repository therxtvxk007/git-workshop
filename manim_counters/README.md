# Counters — Manim video

An animated walkthrough of the DE & LD class notes on **Counters**: an introduction,
followed by asynchronous binary and non-binary up and down counters.

`counters_video.mp4` is the rendered video (1080p, about 5 minutes).

## Scenes

| # | Scene | Covers |
|---|-------|--------|
| 1 | `S01_Intro` | What a counter is, counting clock pulses, n bits → 2ⁿ states / n FFs, up vs down |
| 2 | `S02_UpDownModN` | 2-bit up/down state cycles, Mod-N, `2ⁿ = N`, `n = log₂ N`, Mod-6 example |
| 3 | `S03_BinaryNonBinary` | Binary vs non-binary counters, summary (Mod-4 vs Mod-3/Mod-2) |
| 4 | `S04_AsyncVsSync` | Asynchronous vs synchronous comparison table |
| 5 | `S05_AsyncUp` | 3-bit async up counter (JK, J=K=1, −ve edge), ripple animation, timing diagram |
| 6 | `S06_Observations` | Edge type × Q/Q̄ connection → up/down rule, JK truth table |
| 7 | `S07_Mod5Up` | Mod-5 up counter: clear at 101, truth table, K-map, NAND/AND, circuit demo |
| 8 | `S08_AsyncDown` | 3-bit async down counter (+ve edge), state animation, timing diagram |
| 9 | `S09_Mod5Down` | Mod-5 down counter: preset at 010, K-map, OR/NOR, circuit demo, takeaways |

## Rendering

You need `manim` (Community Edition ≥ 0.18) and `ffmpeg`. LaTeX is **not** required,
because all text is drawn with `Text`.

```bash
pip install manim
./render.sh          # 1080p60 → counters_video.mp4
./render.sh -ql      # quick 480p preview
manim -pql counters.py S07_Mod5Up   # preview a single scene
```
