"""Configuration.

Every expensive component is named here, not hard-wired at the call site. The
defaults are the offline-capable implementations so the whole cascade runs on
CPU with no downloads; a deployment config swaps in Qwen3.8 / Jina v5 / Qdrant /
Neo4j by changing a string, not by editing pipeline code.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- hardware ---

HARDWARE_PROFILES: dict[str, dict[str, Any]] = {
    # Determines which side of every size/quality trade-off we land on.
    "cpu_only": {
        "vram_gb": 0,
        "llm": "stub",
        "llm_quant": None,
        "embedder": "hashing",
        "reranker": "lexical",
        "max_llm_calls_per_run": 0,
        "notes": "Development and CI. Cascade runs end to end; stage 3 degrades "
                 "to the deterministic verifier rather than being skipped.",
    },
    "gpu_24gb": {
        "vram_gb": 24,
        "llm": "qwen3.8-27b",
        "llm_quant": "awq-int4",
        "llm_max_context": 16384,
        "embedder": "jina-v5-small",
        "reranker": "jina-reranker-3.5",
        "max_llm_calls_per_run": 400,
        "notes": "Quantised 27B with restricted context. Extraction and "
                 "retrieval run offline in batch; the LLM is selective only.",
    },
    "gpu_80gb": {
        "vram_gb": 80,
        "llm": "qwen3.8-27b",
        "llm_quant": "fp8",
        "llm_max_context": 65536,
        "embedder": "jina-v5-small",
        "reranker": "jina-reranker-3.5",
        "multimodal_embedder": "qwen3-vl-embedding-8b",
        "multimodal_reranker": "qwen3-vl-reranker-2b",
        "max_llm_calls_per_run": 4000,
        "notes": "Longer evidence contexts, larger batches, QLoRA comfortably, "
                 "multimodal reranker resident concurrently.",
    },
    "cluster": {
        "vram_gb": 640,
        "llm": "qwen3.8-27b",
        "llm_quant": "bf16",
        "llm_max_context": 262144,
        "teacher": "qwen3.8-2.4t-a95b",
        "embedder": "jina-v5-small",
        "multimodal_embedder": "qwen3-vl-embedding-8b",
        "max_llm_calls_per_run": 100000,
        "distributed": "fsdp2",
        "notes": "Teacher generates hypotheses and judges hard cases; distil "
                 "into the 27B operational model. The teacher is not deployed "
                 "per forecast unless it shows a measured gain.",
    },
}

# ------------------------------------------------------------ stage configs ---


@dataclass
class Stage0Config:
    """Remove wasted work before any semantic model touches a document."""

    exact_dedup: bool = True
    minhash_permutations: int = 128
    minhash_bands: int = 32          # bands x rows must equal permutations
    minhash_threshold: float = 0.80  # Jaccard for near-duplicate clustering
    simhash_bits: int = 64
    simhash_hamming_threshold: int = 3
    strip_boilerplate: bool = True
    min_tokens: int = 12
    require_timestamp: bool = True
    max_future_skew_hours: int = 6   # published_at later than this is rejected
    cache_dir: str = ".cache/pramaan"


@dataclass
class Stage1Config:
    """Cheap high-recall scan. Tuned for recall; precision is stage 2-4's job."""

    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    lexical_trigger_percentile: float = 0.85   # keep top 15% by lexical score
    relevance_threshold: float = 0.12          # deliberately low
    relevance_target_recall: float = 0.98      # operating point, set on holdout
    burst_cusum_k: float = 0.5                 # slack, in sigma
    burst_cusum_h: float = 5.0                 # decision interval, in sigma
    burst_cusum_warmup: float = 0.25           # prefix used for in-control estimate
    bocpd_hazard: float = 1 / 120.0            # ~1 changepoint per 120 steps
    bocpd_threshold: float = 0.25
    extractor: str = "rule"                    # "rule" | "gliner-relex"
    extractor_min_type_score: float = 3.0      # floor on the winning type score
    # Burst is *context*, not evidence. A change point in a location raises the
    # prior for documents about that location; on its own it says nothing about
    # any particular document, so it only fires jointly with lexical weight.
    burst_requires_lexical: bool = True
    burst_lexical_percentile: float = 0.85
    gliner_model: str = "knowledgator/gliner-relex-large-v1.0"
    embedder: str = "hashing"                  # "hashing" | "jina-v5-small"
    embed_dim: int = 1024
    # A document is retained if ANY detector fires. Union, not intersection --
    # intersecting detectors is how you lose recall.
    retain_on_any: bool = True
    # Defaults come from a 36-point grid over (extractor floor, lexical
    # percentile, relevance target recall, burst percentile) measured on a held
    # out window: every point held 100% precursor recall, and retention ranged
    # 37%-83%. These settings sit at 39% rather than the sweep minimum of 37%,
    # because tuning to the extreme of a single window is how an operating point
    # stops generalising.


@dataclass
class Stage2Config:
    bm25_top_k: int = 200
    dense_top_k: int = 200
    late_top_k: int = 60
    rerank_top_k: int = 20
    rrf_k: int = 60
    engine: str = "memory"          # "memory" | "qdrant" | "vespa"
    graph_backend: str = "memory"   # "memory" | "kuzu" | "neo4j"
    reranker: str = "lexical"       # "lexical" | "jina-reranker-3.5" | "qwen3-vl-reranker-2b"
    use_learned_fusion: bool = True # LambdaMART over the component scores
    # MTRM horizons, in days. The hazard model learns which one matters per
    # event type rather than us picking a single window.
    mtrm_horizons: tuple[int, ...] = (1, 3, 7, 30, 90, 365)
    # LANTERN windows.
    lantern_long_days: int = 180
    lantern_short_days: int = 14
    lantern_evidence_budget: int = 12   # Pareto-greedy selection budget
    ithi_max_per_type: int = 8


@dataclass
class Stage3Config:
    """Expensive reasoning. Every knob here exists to make it rarer."""

    provider: str = "stub"          # "stub" | "vllm" | "sglang" | "openai"
    base_url: str = "http://localhost:8000/v1"
    model: str = "Qwen/Qwen3.8-27B"
    teacher_model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 768
    timeout_s: float = 60.0
    # Routing: only these cases reach the LLM.
    ambiguity_threshold: float = 0.55   # extractor confidence below this
    scatter_samples: int = 6            # diverse futures per invoked target
    scatter_temperature: float = 0.95
    max_calls: int = 0                  # 0 = unlimited (bounded by profile)
    cache_responses: bool = True


@dataclass
class Stage4Config:
    tabular_models: tuple[str, ...] = ("lightgbm", "xgboost", "catboost")
    n_folds: int = 5                    # out-of-fold stacking
    hazard_hidden: tuple[int, ...] = (64, 32)
    hazard_epochs: int = 120
    hazard_lr: float = 3e-3
    hazard_intervals: int = 6           # discrete time intervals
    use_aft: bool = True                # XGBoost AFT survival baseline
    openset_evt_tail_frac: float = 0.10
    calibrators: tuple[str, ...] = ("isotonic", "venn_abers", "temperature")
    random_state: int = 20260824


@dataclass
class Stage5Config:
    epsilon: float = 0.10     # target upper bound on false-negative risk
    delta: float = 0.10       # confidence level for the bound (1 - delta)
    lambda_grid: int = 200    # resolution of the CRC threshold search
    limited_fp_budget: float = 0.35   # max fraction of the universe in the set
    alert_probability: float = 0.60
    alert_min_independent_sources: int = 2
    watch_probability: float = 0.25
    ledger_path: str = "artifacts/ledger.jsonl"


@dataclass
class EvalConfig:
    temporal_folds: int = 4
    embargo_days: int = 7      # gap between train and test to kill leakage
    required_recall: float = 1.0
    ndcg_k: int = 10
    recall_k: int = 50


@dataclass
class Config:
    hardware_profile: str = "cpu_only"
    seed: int = 20260824
    horizon_days: int = 7
    artifacts_dir: str = "artifacts"
    tracking: str = "local"     # "local" | "mlflow"
    mlflow_uri: str = "http://localhost:5000"
    experiment: str = "pramaan-x"

    stage0: Stage0Config = field(default_factory=Stage0Config)
    stage1: Stage1Config = field(default_factory=Stage1Config)
    stage2: Stage2Config = field(default_factory=Stage2Config)
    stage3: Stage3Config = field(default_factory=Stage3Config)
    stage4: Stage4Config = field(default_factory=Stage4Config)
    stage5: Stage5Config = field(default_factory=Stage5Config)
    eval: EvalConfig = field(default_factory=EvalConfig)

    def __post_init__(self) -> None:
        if self.hardware_profile not in HARDWARE_PROFILES:
            raise ValueError(
                f"unknown hardware profile {self.hardware_profile!r}; "
                f"choose one of {sorted(HARDWARE_PROFILES)}"
            )
        s0 = self.stage0
        if s0.minhash_permutations % s0.minhash_bands:
            raise ValueError(
                f"minhash_bands ({s0.minhash_bands}) must divide "
                f"minhash_permutations ({s0.minhash_permutations})"
            )
        if not 0 < self.stage5.epsilon < 1:
            raise ValueError("stage5.epsilon must lie in (0, 1)")
        if not 0 < self.stage5.delta < 1:
            raise ValueError("stage5.delta must lie in (0, 1)")

    @property
    def profile(self) -> dict[str, Any]:
        return HARDWARE_PROFILES[self.hardware_profile]

    def apply_profile(self) -> Config:
        """Let the hardware profile drive component selection. Explicit stage
        settings still win -- this only fills what the profile knows better."""
        p = self.profile
        self.stage1.embedder = p.get("embedder", self.stage1.embedder)
        self.stage2.reranker = p.get("reranker", self.stage2.reranker)
        llm = p.get("llm", "stub")
        self.stage3.provider = "stub" if llm == "stub" else self.stage3.provider
        if llm != "stub":
            self.stage3.model = {
                "qwen3.8-27b": "Qwen/Qwen3.8-27B",
            }.get(llm, llm)
        if p.get("teacher"):
            self.stage3.teacher_model = "Qwen/Qwen3.8-2.4T-A95B"
        self.stage3.max_calls = int(p.get("max_llm_calls_per_run", 0))
        return self

    # ------------------------------------------------------------ io ---

    def to_dict(self) -> dict[str, Any]:
        return _as_plain(asdict(self))

    def fingerprint(self) -> str:
        """Stable hash of the whole configuration, recorded with every run so a
        result can never be silently attributed to a different setup."""
        import hashlib

        blob = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Config:
        sections = {
            "stage0": Stage0Config, "stage1": Stage1Config, "stage2": Stage2Config,
            "stage3": Stage3Config, "stage4": Stage4Config, "stage5": Stage5Config,
            "eval": EvalConfig,
        }
        kwargs: dict[str, Any] = {k: v for k, v in raw.items() if k not in sections}
        for name, klass in sections.items():
            if name in raw and raw[name] is not None:
                fields = set(klass.__dataclass_fields__)
                unknown = set(raw[name]) - fields
                if unknown:
                    raise ValueError(f"unknown keys in [{name}]: {sorted(unknown)}")
                kwargs[name] = klass(**_retuple(klass, raw[name]))
        return cls(**kwargs)

    @classmethod
    def load(cls, path: str | Path) -> Config:
        path = Path(path)
        raw = json.loads(path.read_text()) if path.suffix == ".json" else _load_yaml(path)
        return cls.from_dict(raw or {}).apply_profile()

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, default=str))


def _retuple(klass: type, values: dict[str, Any]) -> dict[str, Any]:
    """YAML gives lists where the dataclass declares tuples; normalise so that
    config equality and fingerprints stay stable across load round-trips."""
    out = dict(values)
    for name, f in klass.__dataclass_fields__.items():
        if name in out and isinstance(out[name], list) and "tuple" in str(f.type):
            out[name] = tuple(out[name])
    return out


def _as_plain(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return _as_plain(asdict(obj))
    if isinstance(obj, dict):
        return {k: _as_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_as_plain(v) for v in obj]
    return obj


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(path.read_text())
