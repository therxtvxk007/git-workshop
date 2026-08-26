"""Configuration loading.

Configuration is data, not code: every run records the hash of the fully
resolved configuration so an experiment can be replayed exactly. Layering is
``base.yaml`` -> included files -> environment variables -> explicit overrides,
with later layers winning.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from pramaanx.hashing import hash_object

ENV_PREFIX = "PRAMAANX_"
DEFAULT_CONFIG_PATH = Path("configs/base.yaml")


class ConfigModel(BaseModel):
    """Base for every configuration block.

    ``extra="forbid"`` is on the base class rather than on each block, because
    the failure it prevents is silent: a typo like ``match_min_socre`` in a YAML
    file would otherwise be ignored, the default would apply, and the run would
    report metrics computed under a threshold nobody chose. A config typo has to
    be an error, not a shrug.
    """

    model_config = ConfigDict(extra="forbid")


class StorageConfig(ConfigModel):
    data_root: Path = Path("data")
    run_root: Path = Path("runs")
    parquet_compression: str = "zstd"
    payload_shard_depth: int = Field(default=2, ge=1, le=4)

    @property
    def bronze(self) -> Path:
        return self.data_root / "bronze"

    @property
    def silver(self) -> Path:
        return self.data_root / "silver"

    @property
    def gold(self) -> Path:
        return self.data_root / "gold"

    @property
    def snapshots(self) -> Path:
        return self.data_root / "snapshots"


class TimeguardConfig(ConfigModel):
    """Cutoff safety is a model feature, not merely an evaluation option."""

    strict: bool = True
    # A body edited after the cutoff cannot be used at the cutoff, even when the
    # URL is old. Connectors record retrieved_at so this stays checkable.
    reject_updated_bodies: bool = True
    retrospective_markers: list[str] = Field(
        default_factory=lambda: [
            "after the attack",
            "in the aftermath",
            "following the blast",
            "died in the attack",
            "the incident occurred",
            "was later confirmed",
            "in hindsight",
            "as it turned out",
            "the death toll rose",
            "has since been",
        ]
    )
    max_future_skew_seconds: int = 0


class GeneratorConfig(ConfigModel):
    """Which candidate generators run, and with what proposal budget.

    M0 ships one generator (``base_rate``). The list exists so that adding G1-G7
    later is a config change plus a registration, not a rewrite.
    """

    enabled: list[str] = Field(default_factory=lambda: ["base_rate"])
    proposal_budget: int = Field(default=500, gt=0)
    # Shares are normalised over the generators actually enabled, so disabling a
    # branch in an ablation does not silently shrink the total budget.
    budget_shares: dict[str, float] = Field(default_factory=lambda: {"base_rate": 1.0})
    min_generator_score: float = 0.0
    lookback_days: int = Field(default=365, gt=0)
    recent_activity_days: int = Field(default=30, gt=0)


class AlertPolicyConfig(ConfigModel):
    """Placeholder thresholds for the backtest skeleton.

    These are NOT the risk controller. Phase 8 replaces this with recall-first
    conformal risk control, where thresholds are fitted on calibration data and
    locked before test evaluation. Until then these are fixed constants, and no
    operational claim may be based on them. The miss-versus-false-alert
    trade-off is a human decision, not a default.
    """

    alert_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    watch_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    monitor_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    min_evidence_items: int = Field(default=1, ge=0)
    #: Above this novelty score a candidate is held at MONITOR whatever its
    #: probability: a threshold fitted on familiar streams says nothing about
    #: one with no history.
    novelty_monitor_threshold: float = Field(default=0.7, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_ordering(self) -> AlertPolicyConfig:
        if not self.alert_threshold >= self.watch_threshold >= self.monitor_threshold:
            raise ValueError("thresholds must satisfy alert >= watch >= monitor")
        return self


class EvaluationConfig(ConfigModel):
    time_buckets: list[str] = Field(
        default_factory=lambda: ["0-1d", "2-3d", "4-7d", "8-14d", "15-30d", "31-90d"]
    )
    match_time_tolerance_days: float = 3.0
    match_min_score: float = Field(default=0.6, ge=0.0, le=1.0)
    proposal_budgets: list[int] = Field(default_factory=lambda: [50, 100, 250, 500])
    alerts_per_region_day: float = Field(default=5.0, gt=0.0)
    #: Floor on how long after an event its first legitimate report may arrive.
    #: The backtest requires evidence through
    #: ``final cutoff + horizon + max(this, the empirical maximum)`` before it
    #: will score a fold; anything shorter is right-censored, and missing
    #: reports are indistinguishable from events that never happened.
    max_reporting_delay_days: float = Field(default=3.0, ge=0.0)
    reliability_bins: int = Field(default=10, gt=1)
    step_days: int = Field(default=7, gt=0)


class SourceOptions(ConfigModel):
    """Base for a connector's configuration block.

    Source options live here, next to the rest of the configuration schema,
    rather than beside their connectors. Validating them requires knowing every
    source before any connector is imported, and a registry populated by import
    side effects would make validation depend on import order -- so a typo would
    be caught or missed depending on what else the process had loaded.
    """


class SyntheticSourceConfig(SourceOptions):
    """Options for the deterministic synthetic world."""

    #: Defaults to ``Settings.random_seed`` when unset.
    seed: int | None = None
    world_start: datetime | None = None
    world_end: datetime | None = None
    noise_per_day: float = Field(default=3.0, ge=0.0)


class GdeltSourceConfig(SourceOptions):
    """Options for the GDELT 2.0 Events connector."""

    base_url: str = "https://data.gdeltproject.org/gdeltv2"
    #: How long after its 15-minute slot an export file is treated as
    #: observable. Conservative on purpose; see the connector's docstring.
    publication_lag_minutes: int = Field(default=15, ge=0)
    #: 0 means no limit. Unfiltered ingestion is ~2000 rows per file.
    max_rows_per_file: int = Field(default=0, ge=0)
    country_filter: list[str] = Field(default_factory=list)
    event_root_codes: list[str] = Field(default_factory=list)
    #: Gaps in the archive are normal; a silent gap is not, so they are logged.
    skip_missing_files: bool = True

    # -- egress ----------------------------------------------------------
    cache: bool = True
    timeout_seconds: float = Field(default=60.0, gt=0.0)
    max_attempts: int = Field(default=4, ge=1)
    backoff_seconds: float = Field(default=2.0, ge=0.0)
    #: Explicit proxy URL (http://, https:// or socks5://). Overrides the
    #: environment; ``None`` means "use whatever the environment says".
    proxy: str | None = None
    trust_env: bool = True
    ca_bundle: str | None = None
    verify: bool = True


#: The source names this milestone knows about, and the shape of each one's
#: options. Adding a connector means adding an entry here, which is deliberate:
#: an unregistered source name is a typo until someone says otherwise.
SOURCE_OPTION_MODELS: dict[str, type[SourceOptions]] = {
    "synthetic": SyntheticSourceConfig,
    "gdelt": GdeltSourceConfig,
}


class Settings(ConfigModel):
    """Fully resolved run configuration."""

    version: int = 1
    random_seed: int = 20260825
    horizon_days: int = 90
    log_level: str = "INFO"
    log_format: str = "console"
    storage: StorageConfig = Field(default_factory=StorageConfig)
    timeguard: TimeguardConfig = Field(default_factory=TimeguardConfig)
    generators: GeneratorConfig = Field(default_factory=GeneratorConfig)
    alerting: AlertPolicyConfig = Field(default_factory=AlertPolicyConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    #: Per-source options, validated against the model registered for each
    #: source name. Stored as plain mappings so the config hash covers exactly
    #: the values that were written; validation happens in the validator below.
    sources: dict[str, dict[str, Any]] = Field(default_factory=dict)
    extras: dict[str, Any] = Field(default_factory=dict)

    @field_validator("log_format")
    @classmethod
    def _check_log_format(cls, value: str) -> str:
        if value not in {"console", "json"}:
            raise ValueError("log_format must be 'console' or 'json'")
        return value

    @model_validator(mode="after")
    def _validate_sources(self) -> Settings:
        """Reject unknown source names and unknown source options at load time.

        A misspelled option -- ``publication_lag_minuts`` -- is the quietest
        failure in the system: the connector reads its default, ingestion
        succeeds, and every downstream timestamp is wrong by whatever the
        operator thought they had configured. Failing here, rather than when
        ingestion eventually runs, means `pramaanx version` catches it.
        """
        for source_id, options in self.sources.items():
            model = SOURCE_OPTION_MODELS.get(source_id)
            if model is None:
                known = ", ".join(sorted(SOURCE_OPTION_MODELS))
                raise ValueError(
                    f"unknown source {source_id!r} in 'sources'; this milestone knows: {known}"
                )
            try:
                model.model_validate(options)
            except ValidationError as error:
                # Re-raised with the source name in the path, so the message
                # points at sources.gdelt.publication_lag_minuts rather than at
                # a bare field name with no indication of where it came from.
                raise ValueError(
                    f"invalid options for source {source_id!r}: "
                    + "; ".join(
                        f"{'.'.join(str(part) for part in item['loc']) or '<root>'}: {item['msg']}"
                        for item in error.errors()
                    )
                ) from error
        return self

    def source_options(self, source_id: str) -> SourceOptions:
        """Validated options for one source, defaults filled in."""
        model = SOURCE_OPTION_MODELS.get(source_id)
        if model is None:
            known = ", ".join(sorted(SOURCE_OPTION_MODELS))
            raise KeyError(f"unknown source {source_id!r}; this milestone knows: {known}")
        return model.model_validate(self.sources.get(source_id, {}))

    @property
    def config_hash(self) -> str:
        """Hash of the resolved configuration, recorded in every manifest."""
        return hash_object(self.model_dump(mode="json"))


def _deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _coerce_env_value(raw: str) -> Any:
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError:
        return raw


def _env_overrides(environ: Mapping[str, str]) -> dict[str, Any]:
    """Map ``PRAMAANX_STORAGE__DATA_ROOT`` style variables onto nested keys.

    A handful of single-word aliases are kept for the variables people type by
    hand (``PRAMAANX_DATA_ROOT``, ``PRAMAANX_LOG_LEVEL``).
    """
    aliases = {
        "DATA_ROOT": ("storage", "data_root"),
        "RUN_ROOT": ("storage", "run_root"),
        "LOG_LEVEL": ("log_level",),
        "LOG_FORMAT": ("log_format",),
        "RANDOM_SEED": ("random_seed",),
    }
    overrides: dict[str, Any] = {}
    for raw_key, raw_value in environ.items():
        if not raw_key.startswith(ENV_PREFIX):
            continue
        suffix = raw_key.removeprefix(ENV_PREFIX)
        if suffix in aliases:
            path = aliases[suffix]
        elif "__" in suffix:
            path = tuple(part.lower() for part in suffix.split("__"))
        else:
            continue  # source credentials are read by connectors, not by Settings
        cursor = overrides
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = _coerce_env_value(raw_value)
    return overrides


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config file must contain a mapping: {path}")
    return data


def _resolve_includes(data: dict[str, Any], base_dir: Path, seen: set[Path]) -> dict[str, Any]:
    includes = data.pop("include", []) or []
    if isinstance(includes, str):
        includes = [includes]
    resolved: dict[str, Any] = {}
    for entry in includes:
        path = (base_dir / entry).resolve()
        if path in seen:
            raise ValueError(f"circular config include: {path}")
        seen.add(path)
        child = _resolve_includes(_load_yaml(path), path.parent, seen)
        resolved = _deep_merge(resolved, child)
    return _deep_merge(resolved, data)


def load_settings(
    path: Path | str | None = None,
    *,
    overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """Load, layer and validate configuration into :class:`Settings`."""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    data: dict[str, Any] = {}
    if config_path.exists():
        data = _resolve_includes(
            _load_yaml(config_path), config_path.parent, {config_path.resolve()}
        )
    data = _deep_merge(data, _env_overrides(os.environ if environ is None else environ))
    if overrides:
        data = _deep_merge(data, overrides)
    return Settings.model_validate(data)


def dotted_overrides(pairs: Iterable[str]) -> dict[str, Any]:
    """Turn ``risk.target_recall=0.95`` strings into a nested override mapping."""
    overrides: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"override must look like key.path=value, got {pair!r}")
        key, _, raw = pair.partition("=")
        cursor = overrides
        parts = key.strip().split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = _coerce_env_value(raw.strip())
    return overrides
