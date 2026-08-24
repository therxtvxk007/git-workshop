"""Command-line interface.

    evpred demo                             # simulated end-to-end backtest
    evpred backtest --csv news.csv --acled acled.csv
    evpred extract --text "the union threatened a strike"

``backtest`` is the entry point for real corpora: point it at a document source
and a realised-event catalogue and it runs the same walk-forward evaluation the
demo runs, with the same baselines.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys

import numpy as np

from .adapters import build_labels, deduplicate, load_acled_events, load_csv, load_jsonl
from .backtest import BacktestConfig, run_backtest, summarise
from .evidence import precursor_report
from .extraction import get_extractor
from .stacking import HybridConfig
from .synthetic import SimConfig, make_dataset


def _cmd_demo(args: argparse.Namespace) -> int:
    sim, documents, labels = make_dataset(
        SimConfig(n_regions=args.regions, n_days=args.days, seed=args.seed)
    )
    print(f"simulated {len(documents)} documents across {args.regions} regions")
    result = run_backtest(
        documents,
        labels,
        BacktestConfig(
            n_folds=args.folds,
            min_train_origins=args.min_train,
            lookback_days=args.lookback,
            horizon_days=args.horizon,
            verbose=not args.quiet,
        ),
        model_config=HybridConfig(
            lookback_days=args.lookback, half_life_days=args.half_life
        ),
    )
    print("\n" + summarise(result))
    return 0


def _cmd_backtest(args: argparse.Namespace) -> int:
    documents = []
    if args.csv:
        documents += load_csv(
            args.csv, text_col=args.text_col, date_col=args.date_col,
            region_col=args.region_col, source="csv",
        )
    if args.jsonl:
        documents += load_jsonl(
            args.jsonl, text_key=args.text_col, date_key=args.date_col,
            region_key=args.region_col, source="jsonl",
        )
    if not documents:
        print("no documents loaded; pass --csv and/or --jsonl", file=sys.stderr)
        return 2
    if args.dedup:
        before = len(documents)
        documents = deduplicate(documents)
        print(f"deduplicated {before} -> {len(documents)} documents")

    regions = sorted({d.region for d in documents})
    dates = sorted({d.date for d in documents})
    origins = [
        d for d in dates
        if d - _dt.timedelta(days=args.lookback) >= dates[0]
        and d + _dt.timedelta(days=args.horizon) <= dates[-1]
    ]
    if args.acled:
        events = load_acled_events(args.acled, region_col=args.region_col)
        labels = build_labels(events, regions, origins, args.horizon)
    else:
        print("no --acled label source given; cannot score a backtest", file=sys.stderr)
        return 2

    positives = sum(labels.values())
    print(f"{len(documents)} documents, {len(regions)} regions, {len(origins)} origins, "
          f"{positives} positive windows (base rate {positives / max(1, len(labels)):.3f})")

    result = run_backtest(
        documents,
        labels,
        BacktestConfig(
            n_folds=args.folds, min_train_origins=args.min_train,
            lookback_days=args.lookback, horizon_days=args.horizon,
            verbose=not args.quiet,
        ),
        model_config=HybridConfig(
            lookback_days=args.lookback, half_life_days=args.half_life
        ),
        extractor=get_extractor(args.extractor),
    )
    print("\n" + summarise(result))

    if args.evidence:
        print("\ntop forecasts with evidence:")
        for f in sorted(result.forecasts, key=lambda f: -f.probability)[: args.evidence]:
            print(precursor_report(f))
            print()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "pooled": result.pooled,
                    "branches": result.pooled_branches,
                    "baselines": result.pooled_baselines,
                    "conformal": result.pooled_conformal,
                    "forecasts": [
                        {
                            "region": f.region, "origin": f.origin.isoformat(),
                            "probability": f.probability, "label": f.label,
                            "abstained": f.abstained,
                            "precursors": [
                                {"doc_id": p.doc_id, "date": p.date.isoformat(),
                                 "score": p.score, "snippet": p.snippet}
                                for p in f.precursors
                            ],
                        }
                        for f in result.forecasts
                    ],
                },
                fh,
                indent=2,
                default=float,
            )
        print(f"wrote {args.out}")
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    extractor = get_extractor(args.extractor)
    text = args.text if args.text else sys.stdin.read()
    events = extractor.extract(text)
    print(f"extractor: {getattr(extractor, 'name', type(extractor).__name__)}")
    if not events:
        print("no events extracted")
        return 0
    for e in events:
        print(f"  {e.action:<14} actor={e.actor or '-':<18} target={e.target or '-':<18} "
              f"pol={e.polarity:+.2f} conf={e.confidence:.2f} time={e.time_ref or '-'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evpred",
        description="Hybrid LLM + classical ML event prediction from unstructured text",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--lookback", type=int, default=14)
        p.add_argument("--horizon", type=int, default=7)
        p.add_argument("--folds", type=int, default=4)
        p.add_argument("--min-train", type=int, default=90)
        p.add_argument("--half-life", type=float, default=5.0)
        p.add_argument("--quiet", action="store_true")

    d = sub.add_parser("demo", help="run the simulated end-to-end backtest")
    d.add_argument("--regions", type=int, default=6)
    d.add_argument("--days", type=int, default=300)
    d.add_argument("--seed", type=int, default=0)
    add_common(d)
    d.set_defaults(func=_cmd_demo)

    b = sub.add_parser("backtest", help="backtest on a real corpus")
    b.add_argument("--csv")
    b.add_argument("--jsonl")
    b.add_argument("--acled", help="ACLED export supplying realised-event labels")
    b.add_argument("--text-col", default="text")
    b.add_argument("--date-col", default="date")
    b.add_argument("--region-col", default="region")
    b.add_argument("--extractor", default="auto", choices=["auto", "rule", "llm"])
    b.add_argument("--dedup", action="store_true")
    b.add_argument("--evidence", type=int, default=0, metavar="N")
    b.add_argument("--out", help="write results as JSON")
    add_common(b)
    b.set_defaults(func=_cmd_backtest)

    e = sub.add_parser("extract", help="extract event tuples from text")
    e.add_argument("--text", help="text to extract from (default: stdin)")
    e.add_argument("--extractor", default="auto", choices=["auto", "rule", "llm"])
    e.set_defaults(func=_cmd_extract)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
