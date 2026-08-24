"""Command line interface.

Drives the same `PramaanService` the API does, so a result obtained from the
shell and one obtained over HTTP came from identical code.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from .config import HARDWARE_PROFILES, Config
from .eval.artefact import BENCHMARK_RESULTS_DIR
from .service import NotReady, PramaanService
from .util.logging import configure, get_logger

log = get_logger("cli")


def _config(args) -> Config:
    cfg = Config.load(args.config) if args.config else Config()
    if args.profile:
        cfg.hardware_profile = args.profile
    return cfg.apply_profile()


def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def cmd_profiles(_args) -> int:
    for name, p in HARDWARE_PROFILES.items():
        print(f"\n{name}  ({p['vram_gb']} GB VRAM)")
        print(f"  llm        {p.get('llm')}  quant={p.get('llm_quant')}")
        print(f"  embedder   {p.get('embedder')}")
        print(f"  llm budget {p.get('max_llm_calls_per_run')} calls/run")
        print(f"  {p['notes']}")
    return 0


def cmd_config(args) -> int:
    cfg = _config(args)
    if args.out:
        cfg.save(args.out)
        print(f"wrote {args.out} (fingerprint {cfg.fingerprint()})")
    else:
        print(json.dumps(cfg.to_dict(), indent=2))
    return 0


def cmd_ingest(args) -> int:
    svc = PramaanService(_config(args))
    status = svc.load_synthetic(days=args.days, seed=args.seed)
    print(json.dumps(status, indent=2, default=str))
    return 0


def cmd_search(args) -> int:
    svc = PramaanService(_config(args))
    svc.load_synthetic(days=args.days)
    try:
        out = svc.search(args.query, as_of=_iso(args.as_of), k=args.k,
                         stop_after=args.stop_after)
    except NotReady as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0
    c = out["cascade"]
    print(f"\ncascade  corpus {c['narrowing'][0]} -> sparse/dense {c['narrowing'][1]} "
          f"-> late {c['narrowing'][2]} -> rerank {c['narrowing'][3]}")
    print(f"timings  {c['timings_ms']}\n")
    for hit in out["results"]:
        print(f"{hit['score']:8.3f}  {hit['doc_id']}  {hit['published_at'][:10]}  "
              f"{hit['source_family']}")
        print(f"          {hit['span'][:110]}")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from .api import create_app

    uvicorn.run(create_app(_config(args)), host=args.host, port=args.port)
    return 0


def _seeds(raw: str, default: int) -> list[int]:
    if not raw:
        return [default]
    return [int(x) for x in raw.replace(",", " ").split()]


def cmd_bench(args) -> int:
    """oracle_target_retrieval.

    Measures precursor-evidence retrieval for a target whose location and
    event type are GIVEN. It is not an event-forecasting evaluation and no
    number it prints may be reported as one.
    """
    import json as _json

    from .eval.artefact import aggregate
    from .eval.harness import prepare, run_method
    from .eval.oracle_target_retrieval import LEGACY, STRICT, format_table
    from .tracking import build_tracker

    cfg = _config(args)
    methods = [{"strict": STRICT, "legacy": LEGACY}[m]
               for m in args.methods.replace(",", " ").split()]
    seeds = _seeds(args.seeds, cfg.seed)
    stages = tuple(args.stages.replace(",", " ").split())
    tracker = build_tracker(cfg.tracking, uri=cfg.mlflow_uri,
                            experiment=cfg.experiment,
                            root=f"{cfg.artifacts_dir}/runs")

    print("oracle_target_retrieval")
    print("  assumes the target location and event type are already known.")
    print("  measures precursor-evidence retrieval only.")
    print("  NOT an event-forecasting evaluation.\n")

    collected: dict[str, list[dict]] = {m: [] for m in methods}
    for seed in seeds:
        prep = prepare(cfg, days=args.days, seed=seed,
                       n_locations=args.locations, n_event_types=args.event_types,
                       embargo_days=cfg.eval.embargo_days,
                       origin_stride_days=args.origin_stride)
        proto = prep.protocol
        print(f"seed {seed}  corpus {len(prep.corpus)} canonical documents  "
              f"protocol {proto.fingerprint()}")
        print(f"  train  {proto.train_start.date()} -> {proto.train_end.date()}   "
              f"embargo {proto.effective_embargo_days}d")
        print(f"  calib  {proto.calibration_start.date()} -> {proto.calibration_end.date()}")
        print(f"  TEST   {proto.test_start.date()} -> {proto.test_end.date()}  "
              f"({len(proto.origins('test'))} forecast origins, locked)")
        for method in methods:
            run_name = f"oracle_target_retrieval:{method}:seed{seed}"
            tracker.start_run(run_name, {"method": method, "seed": str(seed),
                                         "benchmark": "oracle_target_retrieval"})
            try:
                res = run_method(prep, cfg, method, stages=stages,
                                 use_fusion=not args.no_fusion,
                                 results_dir=args.results_dir)
                tracker.log_params({
                    "seed": seed, "days": args.days, "method": method,
                    "protocol_fingerprint": proto.fingerprint(),
                    "config_fingerprint": cfg.fingerprint(),
                    "dataset_logical_hash": prep.dataset.logical_hash,
                })
                final = res.outcome.reports[stages[-1]]
                tracker.log_metrics({k: v for k, v in final.summary().items()
                                     if isinstance(v, (int, float))})
                if res.path is not None:
                    tracker.log_artifact(res.path, kind="benchmark_artefact")
            except Exception:
                tracker.end_run("FAILED")
                raise
            tracker.end_run()
            print()
            print(format_table(res.outcome.reports, cfg=cfg.stage2, method=method))
            viol = res.payload["availability_violations"]
            print(f"  queries       {len(res.train_queries)} train / "
                  f"{len(res.test_queries)} test")
            print(f"  index builds  {res.outcome.n_index_builds}")
            print(f"  availability violations  {viol['total']}  {viol['by_reason']}")
            for name, verdict in res.payload["invariants"].items():
                print(f"  invariant {name:32s} {verdict[:70]}")
            print(f"  artefact      {res.path}")
            collected[method].append(res.payload)
        print()

    summary: dict[str, object] = {"benchmark": "oracle_target_retrieval",
                                  "stage": stages[-1], "seeds": seeds,
                                  "methods": {}}
    for method, payloads in collected.items():
        if not payloads:
            continue
        agg = aggregate(payloads, stage=stages[-1])
        summary["methods"][method] = agg
        print(f"{method}  ({agg['n_seeds']} seeds, stop point {stages[-1]})")
        print(f"  {'metric':<22}{'mean':>9}{'std':>9}{'min':>9}{'max':>9}")
        for k in ("recall@10", "recall@100", "precision@10", "ndcg@10", "mrr"):
            st = agg["statistics"].get(k)
            if st:
                print(f"  {k:<22}{st['mean']:>9.4f}{st['std']:>9.4f}"
                      f"{st['min']:>9.4f}{st['max']:>9.4f}")
        for row in agg["per_seed"]:
            m = row["metrics"]
            print(f"    seed {row['seed']:<12} R@10 {m.get('recall@10', float('nan')):.4f}"
                  f"  nDCG@10 {m.get('ndcg@10', float('nan')):.4f}"
                  f"  MRR {m.get('mrr', float('nan')):.4f}")
        print()

    out = Path(args.results_dir) / "summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n")
    print(f"summary written to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pramaan",
        description="PRAMAAN-X evidence retrieval cascade (stages 0-3). "
                    "Stages 4 and 5 are not implemented; this system does not forecast events.")
    parser.add_argument("--config", help="path to a YAML or JSON config")
    parser.add_argument("--profile", choices=sorted(HARDWARE_PROFILES),
                        help="hardware profile; overrides the config")
    parser.add_argument("--log-level", default="INFO")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("profiles", help="list hardware profiles").set_defaults(fn=cmd_profiles)

    p = sub.add_parser("config", help="print or write the resolved config")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_config)

    p = sub.add_parser("ingest", help="build and index a synthetic corpus")
    p.add_argument("--days", type=int, default=240)
    p.add_argument("--seed", type=int)
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("search", help="run the retrieval cascade")
    p.add_argument("query")
    p.add_argument("--days", type=int, default=240)
    p.add_argument("--as-of", dest="as_of", help="forecast origin, ISO 8601")
    p.add_argument("-k", type=int, default=10)
    p.add_argument("--stop-after", default="rerank",
                   choices=["sparse", "dense", "fusion", "late", "rerank"])
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser(
        "bench",
        help="oracle_target_retrieval: precursor-evidence retrieval for a GIVEN "
             "target. Not a forecasting evaluation.")
    p.add_argument("--days", type=int, default=540)
    p.add_argument("--locations", type=int, default=12)
    p.add_argument("--event-types", dest="event_types", type=int, default=6)
    p.add_argument("--seeds", default="",
                   help="comma or space separated; defaults to the config seed")
    p.add_argument("--methods", default="legacy,strict",
                   help="any of: legacy (contaminated_legacy_diagnostic), "
                        "strict (strict_temporal)")
    p.add_argument("--stages", default="sparse,dense,fusion,late,rerank")
    p.add_argument("--origin-stride", dest="origin_stride", type=int, default=7,
                   help="days between forecast origins in the snapshot grid")
    p.add_argument("--results-dir", dest="results_dir",
                   default=BENCHMARK_RESULTS_DIR)
    p.add_argument("--no-fusion", action="store_true")
    p.set_defaults(fn=cmd_bench)

    p = sub.add_parser("serve", help="run the API and analyst console")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(fn=cmd_serve)

    args = parser.parse_args(argv)
    configure(args.log_level)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
