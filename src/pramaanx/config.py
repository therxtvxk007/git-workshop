"""Configuration loading.

Configuration is data, not code: every run records the hash of the fully
resolved configuration so an experiment can be replayed exactly. Layering is
``base.yaml`` -> included files -> environment variables -> explicit overrides,
with later layers winning.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
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
    #: Fraction of ``lookback_days`` that must actually be covered by evidence
    #: before a rate over that window may be estimated. Below it, generators
    #: abstain. See :mod:`pramaanx.coverage` for why an assumed exposure is a
    #: silent claim that absent records mean absent events.
    min_coverage: float = Field(default=0.8, ge=0.0, le=1.0)


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


#: The ReliefWeb API version this project speaks, in ONE place.
#:
#: The official documentation's endpoint examples are ``https://api.reliefweb.int/v2/reports``
#: (apidoc.reliefweb.int/endpoints, verified 2026-08-26). The URL default below, the
#: ``api_version`` recorded in every payload, and the ``source_version`` stamped on every
#: record and SourceRecord are all derived from this constant, so they cannot drift apart:
#: changing the version here changes all four, and a contract test proves no ``v1`` literal
#: survives anywhere in the tree.
RELIEFWEB_API_VERSION = "v2"
RELIEFWEB_BASE_URL = f"https://api.reliefweb.int/{RELIEFWEB_API_VERSION}"


class ReliefWebSourceConfig(SourceOptions):
    """Options for the ReliefWeb API connector.

    ReliefWeb requires every caller to identify itself with an ``appname``, and
    since 1 November 2025 that name must be **pre-approved** by ReliefWeb --
    it is no longer a string the operator simply picks. Leave it unset here and
    the connector reads ``PRAMAANX_RELIEFWEB_APPNAME`` from the environment;
    setting it here instead puts it inside the config hash, which is useful when
    an experiment should record the identity it called under, and is why no
    tracked config in this repository sets one.
    """

    #: Caller identity: an appname approved by ReliefWeb. ``None`` defers to
    #: PRAMAANX_RELIEFWEB_APPNAME.
    appname: str | None = None
    base_url: str = RELIEFWEB_BASE_URL
    #: The API resource. Phase 1A ingests reports only; /disasters and /jobs
    #: have different date semantics and are not in scope.
    endpoint: Literal["reports"] = "reports"

    # -- query shaping ----------------------------------------------------
    #: Items per request. ReliefWeb caps this; the connector clamps rather
    #: than letting the API reject the whole page.
    page_size: int = Field(default=100, ge=1, le=1000)
    #: 0 means "every page in the window". A cap makes a first run bounded.
    max_items: int = Field(default=0, ge=0)
    #: Hard ceiling on pagination requests, so a mis-specified window cannot
    #: walk the archive indefinitely.
    max_pages: int = Field(default=200, ge=1)
    #: ISO-639-1 codes, e.g. ["en"]. Empty means no language filter.
    languages: list[str] = Field(default_factory=list)
    #: ISO-3166-1 alpha-3 codes, e.g. ["IND"]. Empty means no country filter.
    countries: list[str] = Field(default_factory=list)
    #: ReliefWeb disaster type names, e.g. ["Flood"]. Empty means no filter.
    disaster_types: list[str] = Field(default_factory=list)
    #: Report format names, e.g. ["Situation Report"]. Empty means no filter.
    formats: list[str] = Field(default_factory=list)

    # -- egress -----------------------------------------------------------
    cache: bool = True
    timeout_seconds: float = Field(default=60.0, gt=0.0)
    max_attempts: int = Field(default=4, ge=1)
    backoff_seconds: float = Field(default=2.0, ge=0.0)
    #: Minimum spacing between requests. ReliefWeb rate-limits; pacing is
    #: politeness that also keeps retries from compounding.
    min_interval_seconds: float = Field(default=0.5, ge=0.0)
    #: Ceiling on how long a server-supplied ``Retry-After`` may park the
    #: process. A 429 is an instruction, but an unbounded one is a denial of
    #: service by cooperation: without a cap, a header of 86400 stops an
    #: ingest for a day inside a retry loop nobody is watching.
    max_retry_after_seconds: float = Field(default=60.0, ge=0.0)
    #: Explicit proxy URL (http://, https:// or socks5://). Overrides the
    #: environment; ``None`` means "use whatever the environment says".
    proxy: str | None = None
    trust_env: bool = True
    ca_bundle: str | None = None
    verify: bool = True

    @field_validator("languages")
    @classmethod
    def _check_languages(cls, value: list[str]) -> list[str]:
        for code in value:
            if len(code) != 2 or not code.isalpha():
                raise ValueError(
                    f"language {code!r} is not an ISO-639-1 two-letter code (e.g. 'en')"
                )
        return [code.lower() for code in value]

    @field_validator("countries")
    @classmethod
    def _check_countries(cls, value: list[str]) -> list[str]:
        for code in value:
            if len(code) != 3 or not code.isalpha():
                raise ValueError(f"country {code!r} is not an ISO-3166-1 alpha-3 code (e.g. 'IND')")
        return [code.upper() for code in value]


class DataGovInSourceConfig(SourceOptions):
    """Options for one data.gov.in resource profile.

    The portal exposes heterogeneous tables behind one resource endpoint.  The
    connector is therefore generic, while each YAML profile records the exact
    resource semantics and its independently established availability time.
    Credentials are deliberately absent from this model and come only from
    ``PRAMAANX_DATA_GOV_IN_API_KEY``.
    """

    base_url: str = "https://api.data.gov.in/resource"
    resource_id: str = ""
    resource_title: str = "Unconfigured data.gov.in resource"
    resource_page_url: str = "https://www.data.gov.in/"
    organization: str = "Government of India"
    sector: str = ""
    update_frequency: str = ""
    profile_role: Literal["context_base_rate_only"] = "context_base_rate_only"
    #: The portal shows date precision for the selected resource, not a
    #: timestamp. Preserve those dates rather than manufacturing exact times.
    portal_published_date: date | None = None
    portal_updated_date: date | None = None
    #: A conservative, operator-recorded instant at which this exact resource
    #: version is known to have been available. Required before fetching.
    available_at: datetime | None = None
    #: Optional only for resources with an unambiguous, timezone-aware instant
    #: in every record. Aggregate/year fields must not be placed here.
    claimed_event_time_field: str | None = None
    #: Where a resource has no durable row identifier, the canonical record
    #: hash is the documented stable identity strategy.
    stable_id_fields: list[str] = Field(default_factory=list)
    licence: str = "Government Open Data License - India"
    licence_url: str = "https://www.data.gov.in/government-open-data-license-india"
    redistributable: bool = False

    page_size: Annotated[StrictInt, Field(ge=1, le=1000)] = 100
    max_pages: Annotated[StrictInt, Field(ge=1, le=10000)] = 100
    max_items: Annotated[StrictInt, Field(ge=1, le=1_000_000)] = 10_000

    cache: bool = True
    timeout_seconds: float = Field(default=60.0, gt=0.0)
    max_attempts: Annotated[StrictInt, Field(ge=1, le=10)] = 4
    backoff_seconds: float = Field(default=2.0, ge=0.0)
    max_retry_after_seconds: float = Field(default=60.0, ge=0.0, le=3600.0)
    proxy: str | None = None
    trust_env: bool = True
    ca_bundle: str | None = None
    verify: bool = True

    @field_validator("base_url")
    @classmethod
    def _https_base_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        normalized = value.rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "api.data.gov.in"
            or parsed.path != "/resource"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "base_url must be exactly the documented https://api.data.gov.in/resource endpoint"
            )
        return normalized

    @field_validator("proxy")
    @classmethod
    def _proxy_has_no_inline_credentials(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(
                "proxy credentials must use the environment or external secret manager, "
                "not source config"
            )
        return value

    @field_validator("resource_id")
    @classmethod
    def _resource_uuid(cls, value: str) -> str:
        import uuid

        if not value:
            return value
        try:
            parsed = uuid.UUID(value)
        except ValueError as error:
            raise ValueError("resource_id must be a UUID") from error
        if str(parsed) != value.lower():
            raise ValueError("resource_id must be a canonical UUID")
        return value.lower()

    @field_validator("available_at")
    @classmethod
    def _availability_is_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        return value

    @field_validator("stable_id_fields")
    @classmethod
    def _stable_fields_are_unique(cls, value: list[str]) -> list[str]:
        cleaned = [field.strip() for field in value]
        if any(not field for field in cleaned):
            raise ValueError("stable_id_fields cannot contain blank names")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("stable_id_fields cannot contain duplicates")
        return cleaned

    @field_validator("claimed_event_time_field")
    @classmethod
    def _claimed_field_is_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("claimed_event_time_field cannot be blank")
        return value.strip() if value is not None else None


class AcledSourceConfig(SourceOptions):
    """Options for the credentialed ACLED event API.

    Credential *values* never belong in configuration: only environment-variable
    names do.  Operators may inject a short-lived access token, or let the
    connector perform ACLED's documented OAuth password grant for each ingest.
    """

    base_url: str = "https://acleddata.com/api/acled/read"
    token_url: str = "https://acleddata.com/oauth/token"
    access_token_env: str = Field(
        default="PRAMAANX_ACLED_ACCESS_TOKEN", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"
    )
    username_env: str = Field(
        default="PRAMAANX_ACLED_USERNAME", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"
    )
    password_env: str = Field(
        default="PRAMAANX_ACLED_PASSWORD", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"
    )
    countries: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    page_size: int = Field(default=5000, ge=1, le=5000)
    max_pages: int = Field(default=1000, ge=1)

    # -- egress ----------------------------------------------------------
    timeout_seconds: float = Field(default=60.0, gt=0.0)
    max_attempts: int = Field(default=4, ge=1)
    backoff_seconds: float = Field(default=2.0, ge=0.0)
    max_retry_after_seconds: float = Field(default=60.0, ge=0.0)
    min_interval_seconds: float = Field(default=0.2, ge=0.0)
    proxy: str | None = None
    trust_env: bool = True
    ca_bundle: str | None = None
    verify: bool = True

    @model_validator(mode="after")
    def _https_only(self) -> AcledSourceConfig:
        for name, value in (("base_url", self.base_url), ("token_url", self.token_url)):
            if not value.startswith("https://"):
                raise ValueError(f"{name} must use https")
        return self


#: The source names this milestone knows about, and the shape of each one's
#: options. Adding a connector means adding an entry here, which is deliberate:
#: an unregistered source name is a typo until someone says otherwise.
SOURCE_OPTION_MODELS: dict[str, type[SourceOptions]] = {
    "synthetic": SyntheticSourceConfig,
    "gdelt": GdeltSourceConfig,
    "reliefweb": ReliefWebSourceConfig,
    "acled": AcledSourceConfig,
    "data_gov_in": DataGovInSourceConfig,
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
