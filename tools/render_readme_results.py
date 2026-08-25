"""Generate the README's results section from `benchmark_results/summary.json`.

Every number between the two markers in README.md is written by this script and
by nothing else. The drift this prevents is not hypothetical: the previous
README's latency prose read "33.2 ms mean, 32.6 ms p50, 37.3 ms p95" while the
committed artefacts held 31.54 / 31.25 / 36.05, because a human copied numbers
from one run into prose describing another and nothing compared them
afterwards.

Run it with `--check` in CI: it regenerates the section and fails if the file
on disk differs, which is the same guarantee `ruff format --check` gives for
code.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SUMMARY = ROOT / "benchmark_results" / "summary.json"
README = ROOT / "README.md"
BEGIN = "<!-- BEGIN GENERATED RESULTS -->"
END = "<!-- END GENERATED RESULTS -->"

METRICS = ("recall@10", "recall@20", "recall@50", "recall@100", "precision@10", "ndcg@10", "mrr")


def _artefacts(method: str) -> list[dict[str, Any]]:
    root = ROOT / "benchmark_results" / method
    if not root.exists():
        return []
    out = [json.loads(p.read_text()) for p in sorted(root.rglob("*.json"))]
    for payload, path in zip(out, sorted(root.rglob("*.json")), strict=True):
        payload["_rel"] = str(path.relative_to(ROOT))
    return sorted(out, key=lambda a: a["seed"])


def _stat(values: list[float]) -> str:
    mean = statistics.mean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return f"{mean:.3f} ± {sd:.3f}"


def render() -> str:
    summary = json.loads(SUMMARY.read_text())
    stage = summary["stage"]
    from pramaan_x.eval.oracle_target_retrieval import ABLATION, HISTORICAL, STRICT

    arms = {m: _artefacts(m) for m in (STRICT, ABLATION, HISTORICAL)}
    strict, ablation, historical = arms[STRICT], arms[ABLATION], arms[HISTORICAL]
    if not strict:
        raise SystemExit("no strict_temporal artefacts; run `pramaan bench` first")

    lines: list[str] = [BEGIN, ""]
    w = lines.append
    seeds = [a["seed"] for a in strict]
    first = strict[0]
    w(
        f"Seeds {', '.join(str(s) for s in seeds)}; one synthetic corpus per seed; stop point "
        f"`{stage}`. `mean ± sd` is over {len(seeds)} seeds — a spread from that few runs is "
        "itself noisy, so read it as a spread and not as a confidence interval."
    )
    w("")
    w("### The controlled pair")
    w("")
    w(
        "Identical query ids, text, origins, relevant sets, lexicon, ranker training data, K "
        "values and candidate widths. One variable: whether the index at each origin was fitted "
        "on documents available then, or on the whole corpus."
    )
    w("")
    w(f"| Metric | `{STRICT}` | `{ABLATION}` | Δ of means |")
    w("| --- | --- | --- | --- |")
    for metric in METRICS:
        s_vals = [a["metrics"][stage][metric] for a in strict]
        a_vals = [a["metrics"][stage][metric] for a in ablation]
        delta = statistics.mean(a_vals) - statistics.mean(s_vals)
        w(f"| {metric} | {_stat(s_vals)} | {_stat(a_vals)} | {delta:+.4f} |")
    w("")
    w(
        "**Paired per-query differences** (ablation minus strict, over the shared query "
        "set). This is the number that means something: a difference of means over two query sets is not a "
        "difference of anything."
    )
    w("")
    w("| Metric | mean Δ | sd | queries better | worse | unchanged |")
    w("| --- | --- | --- | --- | --- | --- |")
    paired = [a["extra"]["paired_vs_strict"] for a in ablation if "paired_vs_strict" in a["extra"]]
    if paired:
        for metric in ("recall@10", "recall@100", "precision@10", "ndcg@10", "mrr"):
            means = [p["per_query_delta"][metric]["mean"] for p in paired]
            sds = [p["per_query_delta"][metric]["sd"] for p in paired]
            better = sum(p["per_query_delta"][metric]["n_better"] for p in paired)
            worse = sum(p["per_query_delta"][metric]["n_worse"] for p in paired)
            equal = sum(p["per_query_delta"][metric]["n_equal"] for p in paired)
            w(
                f"| {metric} | {statistics.mean(means):+.4f} | {statistics.mean(sds):.4f} | "
                f"{better} | {worse} | {equal} |"
            )
    w("")
    w("### Per seed")
    w("")
    w(
        "| Seed | Method | R@10 | R@100 | P@10 | nDCG@10 | MRR | Availability violations | "
        "Invariants | Artefact |"
    )
    w("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for seed in seeds:
        for method, runs in ((STRICT, strict), (ABLATION, ablation), (HISTORICAL, historical)):
            match = [a for a in runs if a["seed"] == seed]
            if not match:
                continue
            a = match[0]
            m = a["metrics"][stage]
            n_fail = sum(1 for v in a["invariants"].values() if v.startswith("FAIL"))
            verdict = "all pass" if not n_fail else f"{n_fail}/{len(a['invariants'])} fail"
            w(
                f"| {seed} | `{method}` | {m['recall@10']:.3f} | {m['recall@100']:.3f} | "
                f"{m['precision@10']:.3f} | {m['ndcg@10']:.3f} | {m['mrr']:.3f} | "
                f"{a['availability_violations']['total']} | {verdict} | "
                f"[`{Path(a['_rel']).name}`]({a['_rel']}) |"
            )
    w("")
    w("### The unpaired reproduction")
    w("")
    comparability = historical[0]["extra"]["comparability"] if historical else {}
    w(
        f"`{HISTORICAL}` reproduces the pre-firewall behaviour. It changes "
        f"{', '.join('`' + f + '`' for f in comparability.get('factors_changed', []))} "
        "simultaneously and therefore evaluates a different query set. Its numbers are in the "
        "per-seed table above so the old behaviour can be reproduced; **no delta is computed "
        "against it and none would have a referent.**"
    )
    w("")
    w("### Run shape and latency")
    w("")
    sizes = first["extra"]["fitted_corpus_sizes"]["by_phase"]["evaluation"]
    abl_sizes = (
        ablation[0]["extra"]["fitted_corpus_sizes"]["by_phase"]["evaluation"] if ablation else {}
    )
    sel = first["extra"]["selection"]
    w(
        f"Seed {first['seed']}: {first['n_forecast_origins']} locked forecast origins; "
        f"{first['queries']['test']} test / {first['queries']['train']} training queries; "
        f"{first['queries']['relevant_documents']} relevant documents. The strict arm fits "
        f"{sizes['n_fitted_indexes']} evaluation indexes over {sizes['min']} to {sizes['max']} "
        f"documents (mean {sizes['mean']:.0f}); the ablation fits one over all "
        f"{abl_sizes.get('max', 0)} at every origin."
    )
    w("")
    w(
        f"Operating point chosen on the selection window ({sel['n_selection_queries']} queries, "
        f"{sel['n_candidates_evaluated']} candidates, objective `{sel['objective']}`): "
        f"{', '.join(f'`{k}={v}`' for k, v in sorted(sel['selected'].items()))}."
    )
    w("")
    lat = first["metrics"][stage]
    w(
        f"Latency, strict arm, per query at `{stage}`: mean {lat['latency_ms.mean']:.2f} ms, "
        f"p50 {lat['latency_ms.p50']:.2f} ms, p95 {lat['latency_ms.p95']:.2f} ms "
        f"(seed {first['seed']}; single process, CPU only)."
    )
    w("")
    w(END)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="fail if README.md differs from the generated section"
    )
    args = parser.parse_args()

    generated = render()
    text = README.read_text()
    if BEGIN not in text or END not in text:
        print(f"README.md has no {BEGIN} / {END} markers", file=sys.stderr)
        return 2
    head, rest = text.split(BEGIN, 1)
    _old, tail = rest.split(END, 1)
    updated = head + generated + tail

    if args.check:
        if updated != text:
            print(
                "README.md results section is out of date with "
                "benchmark_results/summary.json.\nRegenerate it with:\n"
                "  uv run python tools/render_readme_results.py",
                file=sys.stderr,
            )
            return 1
        print("README results section matches the artefacts")
        return 0

    README.write_text(updated)
    print(f"wrote the results section of {README.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
