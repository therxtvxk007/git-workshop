# Digital Electronics Lab — Viva Cheat Sheet (Manim video)

An animated walkthrough of the viva cheat sheet. `viva_video.mp4` is the rendered, narrated video (1080p).

| # | Scene | Covers |
|---|-------|--------|
| 1 | `V01_Boolean` | Boolean laws, De Morgan (bubbled-gate equivalents), universal NAND/NOR, propagation delay, gate expressions |
| 2 | `V02_Adders` | Half/full adder truth tables, XOR sum and majority carry, ripple-carry adder demo |
| 3 | `V03_Subtractors` | Half/full subtractor, borrow cases, XOR-controlled adder-subtractor, 5 − 3 worked example |
| 4 | `V04_Overflow` | Unsigned overflow (carry out) and signed overflow (`C(n−1) ⊕ C(n)`) with column addition |
| 5 | `V05_Mux` | 4:1 MUX routing animation and equation, 2:1 MUX, DEMUX |
| 6 | `V06_Decoder` | 2-to-4 decoder lamps, minterms, enable, 3-to-8 expansion, decoder vs MUX |
| 7 | `V07_PriorityEncoder` | Why priority matters, 9-line priority encoder demo, Y4…Y1 expressions |
| 8 | `V08_SevenSeg` | BCD → 7-segment digits 0–9, segment-a K-map, common cathode vs anode |
| 9 | `V09_Sequential` | Latch vs flip-flop timing, characteristic equations, resets, SISO shift register |
| 10 | `V10_Verilog` | Modeling levels, wire/reg, assign/always, blocking vs non-blocking swap, code snippets |
| 11 | `V11_Testbench` | Full-adder testbench, `$monitor`/`$dumpvars`, iverilog + vvp output |

## Rendering

You need `manim` (Community Edition ≥ 0.18) and `ffmpeg`. LaTeX is not required.

### Voiceover

The narration is generated offline with [Kokoro TTS](https://github.com/thewh1teagle/kokoro-onnx).
Each `say(self, "...")` call in the script starts a spoken line, and the page waits until it
finishes. Generated clips are cached in `voiceover/`, so only lines you edit are re-synthesised.

```bash
pip install kokoro-onnx soundfile
mkdir -p ~/.cache/kokoro && cd ~/.cache/kokoro
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

Set `KOKORO_DIR` to keep the model files elsewhere, `VO_VOICE` to change the voice (default `af_heart`,
others include `am_michael` and `bf_emma`), and `VO_SPEED` to change the pace.

```bash
./render.sh          # 1080p60 → viva_video.mp4
./render.sh -ql      # quick 480p preview
```
