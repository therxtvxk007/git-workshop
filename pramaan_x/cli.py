"""Command line interface.

Drives the same `PramaanService` the API does, so a result obtained from the
shell and one obtained over HTTP came from identical code.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from .config import HARDWARE_PROFILES, Config
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


def cmd_bench(args) -> int:
    """Retrieval benchmark. The measurement the design brief requires before
    any retrieval claim is made."""
    from .data.synth import SynthConfig, SyntheticCorpus
    from .eval.retrieval_bench import build_queries, format_table, run_benchmark, train_fusion
    from .stage0_ingest.pipeline import run_stage0
    from .stage1_scan.embed import build_embedder
    from .stage1_scan.lexical import LexicalIndicators
    from .stage2_retrieve.rerank import build_reranker

    cfg = _config(args)
    docs, gt = SyntheticCorpus(SynthConfig(days=args.days, seed=cfg.seed)).generate()
    corpus = run_stage0(docs, cfg.stage0).documents
    start = min(d.published_at for d in corpus)
    end = max(d.published_at for d in corpus)
    split = start + (end - start) * 0.66

    labels, types = [], []
    for d in (t for t in corpus if t.published_at < split):
        key = d.meta.get("synth_target", "none|none")
        _, event_type = key.split("|")
        y = 0
        if event_type != "none":
            for when in gt.events.get(key, []):
                if 0 < (when - d.published_at).days <= 21:
                    y = 1
                    break
        labels.append(y)
        types.append(event_type)

    train_docs = [d for d in corpus if d.published_at < split]
    lexicon = LexicalIndicators().fit([d.full_text for d in train_docs], labels,
                                      event_types=types)
    embedder = build_embedder(cfg.stage1.embedder, cfg.stage1.embed_dim)
    if hasattr(embedder, "fit"):
        embedder.fit([d.full_text for d in corpus])
    reranker = build_reranker(cfg.stage2.reranker)

    train_q = build_queries(gt, lexicon, corpus, window=(start, split))
    test_q = build_queries(gt, lexicon, corpus, window=(split, end))
    print(f"corpus {len(corpus)} canonical documents | "
          f"{len(train_q)} train / {len(test_q)} test queries\n")

    print("heuristic ordering")
    print(format_table(run_benchmark(corpus, test_q, embedder, reranker, cfg=cfg.stage2),
                       cfg=cfg.stage2))
    if not args.no_fusion:
        fusion = train_fusion(corpus, train_q, embedder, reranker, cfg=cfg.stage2)
        print("\nlearned fusion (LambdaMART)")
        print(format_table(
            run_benchmark(corpus, test_q, embedder, reranker, cfg=cfg.stage2,
                          fusion=fusion, stages=("rerank",)), cfg=cfg.stage2))
        print("\nlearned component weights:")
        for k, v in sorted(fusion.weights().items(), key=lambda kv: -kv[1]):
            print(f"  {k:22s} {v:.3f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pramaan", description="PRAMAAN-X compute-cascade event forecasting")
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

    p = sub.add_parser("bench", help="measure Recall@K across cascade stages")
    p.add_argument("--days", type=int, default=300)
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
