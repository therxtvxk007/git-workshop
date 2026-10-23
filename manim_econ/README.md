# Economics class notes, animated with Manim

Animated explainers for four Engineering Economics lectures (Modules 3 & 4).

| Script | Scene | Covers |
|---|---|---|
| `national_income.py` | `NationalIncome` | GDP, final vs intermediate goods, expenditure / income / value-added methods, what's excluded, GDP → GNP → NNP, depreciation, measurement difficulties |
| `inflation.py` | `Inflation` | Definition, village story, 5 causes, effects (incl. on investment & production), monetary / fiscal / supply-side control, repo vs reverse repo |
| `value_engineering.py` | `ValueEngineering` | VA vs VE, origin (Miles, GE, WWII), V = F / C, 4 ways to raise value, cost-vs-value quadrant, types of value, 6-step process, applications, advantages |
| `capital_budgeting.py` | `CapitalBudgeting` | Feasibility, discounted vs non-discounted cash flow, time value of money, NPV (8% vs 15%), IRR curve (≈17.72%), PI (1.07), payback (3.1 yrs), benefit-cost ratio, ARR (4.8%) |

Rendered 1080p videos are in `videos/`.

## Rendering

Needs Manim Community ≥ 0.18 (tested on 0.22). No LaTeX is required: all text goes through Pango.

```bash
pip install manim            # needs pango/cairo dev headers: apt install libpango1.0-dev libcairo2-dev
./render.sh                  # 1080p60 → videos/
./render.sh -ql              # fast 480p preview
manim -pql inflation.py Inflation   # a single scene
```

## Note on the payback example

The notes' working for Q6 (payback period) adds 24,000 + 833.33. The animation uses the
standard method instead: $24,000 is recovered after 3 years, and the remaining $1,000 is
0.1 of year 4's $10,000, so payback ≈ **3.1 years**.
