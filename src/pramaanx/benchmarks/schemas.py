"""Typed benchmark contracts, plans, runs and comparisons.

A benchmark claim is an assertion about someone else's published number. The
only way to make such a claim checkable is to write down, before running
anything, exactly which artefacts it depends on: which commit, which dataset
version, which split, which metric implementation, which seeds. That record is
a :class:`BenchmarkContract`.

Two rules shape every model here.

*Unknown is a value.* A field nobody has verified is ``None`` and carries a
:class:`Blocker` naming it. It is never a plausible-looking guess. A guessed
commit or an invented dataset version does not fail loudly; it produces a run
that looks reproduced and is not.

*Identity is content.* Run identifiers and contract versions are derived from
the bytes that produced them, never from a clock or a counter, so that the same
inputs on another machine land on the same identifier and a changed input
cannot quietly reuse an old one.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Self

from pydantic import Field, model_validator

from pramaanx.hashing import hash_object, stable_id
from pramaanx.schemas.base import PramaanModel, UtcDatetime, VersionedModel

CONTRACT_SCHEMA_VERSION = 1
"""Bump when the *meaning* of a contract field changes.

Distinct from :attr:`BenchmarkContract.contract_version`, which is owned by
whoever edits a single benchmark record.
"""

IMMUTABLE_SHA_LENGTHS = (40, 64)
"""Git object names: 40 hex for SHA-1, 64 for the SHA-256 transition."""


class BenchmarkStatus(StrEnum):
    """Where a benchmark actually stands.

    The enum exists to stop one specific slide: "we have code for it" being
    written up as "we reproduced it". Those are ``not_started`` and
    ``reproduced``, and eleven states separate them.
    """

    NOT_STARTED = "not_started"
    CONTRACT_INCOMPLETE = "contract_incomplete"
    BLOCKED_DATA = "blocked_data"
    BLOCKED_LICENCE = "blocked_licence"
    BLOCKED_ENVIRONMENT = "blocked_environment"
    RUNNING = "running"
    REPRODUCTION_FAILED = "reproduction_failed"
    REPRODUCED = "reproduced"
    CHALLENGER_RUNNING = "challenger_running"
    CHALLENGED_NOT_EXCEEDED = "challenged_not_exceeded"
    EXCEEDED = "exceeded"
    INVALIDATED = "invalidated"


BLOCKED_STATUSES = frozenset(
    {
        BenchmarkStatus.CONTRACT_INCOMPLETE,
        BenchmarkStatus.BLOCKED_DATA,
        BenchmarkStatus.BLOCKED_LICENCE,
        BenchmarkStatus.BLOCKED_ENVIRONMENT,
    }
)

REPRODUCED_OR_BEYOND = frozenset(
    {
        BenchmarkStatus.REPRODUCED,
        BenchmarkStatus.CHALLENGER_RUNNING,
        BenchmarkStatus.CHALLENGED_NOT_EXCEEDED,
        BenchmarkStatus.EXCEEDED,
    }
)


class MetricDirection(StrEnum):
    """Which way is better. A metric without one cannot be compared at all."""

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class ScoreScale(StrEnum):
    """How a published table wrote the number down.

    Hit@1 of ``41.16`` and ``0.4116`` are the same result reported two ways. A
    harness that assumes one convention silently fails reproduction against
    papers using the other, so the convention is recorded per score.
    """

    FRACTION = "fraction"
    PERCENTAGE = "percentage"
    COUNT = "count"
    UNKNOWN = "unknown"


class SourceKind(StrEnum):
    PAPER = "paper"
    REPOSITORY = "repository"
    DATASET = "dataset"
    LEADERBOARD = "leaderboard"
    INTERNAL = "internal"


class BlockerCode(StrEnum):
    """Why a field is empty. Free text hides patterns; a code does not."""

    MISSING_FIELD = "missing_field"
    UNVERIFIED_SOURCE = "unverified_source"
    SOURCE_UNREACHABLE = "source_unreachable"
    LICENCE_UNKNOWN = "licence_unknown"
    LICENCE_FORBIDS_REDISTRIBUTION = "licence_forbids_redistribution"
    DATA_UNAVAILABLE = "data_unavailable"
    ENVIRONMENT_UNAVAILABLE = "environment_unavailable"
    COMPUTE_UNAVAILABLE = "compute_unavailable"
    NO_OFFICIAL_CODE = "no_official_code"
    MUTABLE_REFERENCE = "mutable_reference"
    AWAITING_MEASUREMENT = "awaiting_measurement"
    POLICY_NOT_OPENED = "policy_not_opened"


class FailureClass(StrEnum):
    """What kind of failure a run hit. ``None`` of these is "flaky"."""

    NONE = "none"
    SETUP_FAILED = "setup_failed"
    DATA_MISSING = "data_missing"
    TIMEOUT = "timeout"
    OUT_OF_MEMORY = "out_of_memory"
    NONZERO_EXIT = "nonzero_exit"
    METRIC_PARSE_FAILED = "metric_parse_failed"
    TOLERANCE_EXCEEDED = "tolerance_exceeded"
    POLICY_REFUSED = "policy_refused"


class Blocker(PramaanModel):
    """One named reason a contract is not yet complete.

    ``field`` is the contract field that is missing or unverified, so a report
    can say precisely what would have to be learned to unblock the benchmark.
    """

    field: str
    code: BlockerCode
    detail: str

    def __str__(self) -> str:
        return f"{self.field}: {self.code.value} -- {self.detail}"


class SourceReference(PramaanModel):
    """Where a fact came from, precisely enough to be checked again."""

    kind: SourceKind
    citation: str
    url: str | None = None
    identifier: str | None = None
    """DOI, arXiv id, ACL anthology id, dataset DOI -- whatever is immutable."""

    retrieved_hash: str | None = None
    """Content hash of what was actually fetched, when it was fetched."""


class Period(PramaanModel):
    """A closed date range, or an honest statement that it is not yet known."""

    start: date | None = None
    end: date | None = None
    label: str | None = None

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError(f"period ends {self.end} before it starts {self.start}")
        return self

    @property
    def is_complete(self) -> bool:
        return self.start is not None and self.end is not None

    def overlaps(self, other: Period) -> bool:
        """Whether two known periods share a day. Unknown periods never overlap."""
        if not (self.is_complete and other.is_complete):
            return False
        assert self.start and self.end and other.start and other.end
        return self.start <= other.end and other.start <= self.end


class Tolerance(PramaanModel):
    """How close a reproduction has to land to count.

    Absolute and relative bounds are both optional but at least one is required:
    a tolerance of "close enough" is what this whole package exists to prevent.
    """

    absolute: float | None = Field(default=None, ge=0.0)
    relative: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def _at_least_one_bound(self) -> Self:
        if self.absolute is None and self.relative is None:
            raise ValueError("a tolerance must set an absolute or a relative bound")
        return self

    def contains(self, published: float, observed: float) -> bool:
        delta = abs(observed - published)
        if self.absolute is not None and delta <= self.absolute:
            return True
        if self.relative is not None and published != 0.0:
            return delta / abs(published) <= self.relative
        return False


class PublishedScore(PramaanModel):
    """A number from someone else's paper, with its provenance attached.

    ``verified_against_primary`` is the load-bearing field. It is true only when
    the value was read out of the primary source itself -- the paper's own
    table, the official leaderboard -- not from a summary, a secondary write-up
    or a project design document that quoted it.
    """

    metric: str
    value: float
    scale: ScoreScale
    source: SourceReference
    verified_against_primary: bool = False
    verification_note: str | None = None
    reported_variance: float | None = None
    reported_seed_count: int | None = None

    def as_fraction(self) -> float:
        """Normalise to a fraction where the scale says how to."""
        if self.scale is ScoreScale.PERCENTAGE:
            return self.value / 100.0
        return self.value


class ConfidenceMethod(PramaanModel):
    """How an interval around a difference is produced."""

    name: str
    resamples: int = Field(ge=100)
    alpha: float = Field(gt=0.0, lt=0.5)
    block_length: int | None = Field(default=None, ge=1)
    """Set for temporally dependent units; ``None`` means i.i.d. resampling."""


class PairedTest(PramaanModel):
    """The paired test used to decide whether a difference is real."""

    name: str
    resamples: int = Field(ge=100)
    alternative: str = "greater"


class HardwareRequirements(PramaanModel):
    gpu_count: int = Field(default=0, ge=0)
    gpu_model: str | None = None
    gpu_memory_gb: float | None = Field(default=None, gt=0.0)
    cpu_cores: int | None = Field(default=None, ge=1)
    memory_gb: float | None = Field(default=None, gt=0.0)
    disk_gb: float | None = Field(default=None, gt=0.0)

    @property
    def needs_gpu(self) -> bool:
        return self.gpu_count > 0


class SoftwareEnvironment(PramaanModel):
    """The environment a reproduction must run inside, named concretely."""

    container_image: str | None = None
    container_digest: str | None = None
    python_version: str | None = None
    cuda_version: str | None = None
    environment_files: list[str] = Field(default_factory=list)

    @property
    def is_pinned(self) -> bool:
        """A tag is not an identity; a digest is."""
        return self.container_digest is not None


class CostBudget(PramaanModel):
    """A ceiling on what a run may consume. Reports must never omit cost."""

    gpu_hours: float | None = Field(default=None, ge=0.0)
    cpu_hours: float | None = Field(default=None, ge=0.0)
    wall_clock_hours: float | None = Field(default=None, ge=0.0)
    peak_memory_gb: float | None = Field(default=None, ge=0.0)


class FinalTestPolicy(PramaanModel):
    """The rules under which a frozen test period may ever be read.

    ``opened`` starts false and is only flipped through an authorisation record
    in the access ledger. Nothing in the harness sets it as a side effect.
    """

    opened: bool = False
    authorisation_id: str | None = None
    requires_frozen_contract: bool = True
    requires_frozen_artefacts: bool = True
    requires_frozen_configs: bool = True
    max_openings: int = Field(default=1, ge=1)
    description: str | None = None


class BenchmarkContract(VersionedModel):
    """Everything that has to be true before a benchmark claim means anything.

    The field list is deliberately flat and deliberately long. Each field is
    something that, if left implicit, has already caused someone to publish a
    number they could not defend.
    """

    contract_schema_version: int = CONTRACT_SCHEMA_VERSION
    contract_version: int = Field(default=1, ge=1)
    """Owner-incremented. Changing the metric code or environment requires it."""

    benchmark_id: str
    task_name: str
    benchmark_family: str

    paper_title: str | None = None
    paper_reference: SourceReference | None = None

    official_repository: str | None = None
    official_commit: str | None = None
    official_release_or_tag: str | None = None
    official_code_hash: str | None = None

    data_name: str | None = None
    data_version: str | None = None
    data_hash: str | None = None
    data_license: str | None = None
    redistribution_allowed: bool | None = None

    target_definition: str | None = None
    forecast_horizon: str | None = None
    spatial_unit: str | None = None
    temporal_unit: str | None = None

    training_period: Period | None = None
    validation_period: Period | None = None
    calibration_period: Period | None = None
    test_period: Period | None = None
    split_hash: str | None = None

    primary_metric: str | None = None
    secondary_metrics: list[str] = Field(default_factory=list)
    metric_direction: dict[str, MetricDirection] = Field(default_factory=dict)
    metric_implementation: str | None = None
    metric_code_hash: str | None = None

    published_score: list[PublishedScore] = Field(default_factory=list)
    reproduction_tolerance: dict[str, Tolerance] = Field(default_factory=dict)

    seed_list: list[int] = Field(default_factory=list)
    minimum_seed_count: int | None = Field(default=None, ge=1)
    confidence_method: ConfidenceMethod | None = None
    paired_test: PairedTest | None = None

    hardware_requirements: HardwareRequirements | None = None
    software_environment: SoftwareEnvironment | None = None
    software_lock_hash: str | None = None

    maximum_training_cost: CostBudget | None = None
    maximum_inference_cost: CostBudget | None = None

    final_test_policy: FinalTestPolicy = Field(default_factory=FinalTestPolicy)

    control_run_id: str | None = None
    challenger_run_ids: list[str] = Field(default_factory=list)

    status: BenchmarkStatus = BenchmarkStatus.NOT_STARTED
    blockers: list[Blocker] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _seeds_are_unique(self) -> Self:
        if len(set(self.seed_list)) != len(self.seed_list):
            raise ValueError(f"{self.benchmark_id}: seed_list contains duplicates")
        return self

    def identity_dict(self) -> dict[str, Any]:
        """The fields whose change must change the contract hash.

        Status, blockers, notes and run cross-references are excluded: they
        record progress *against* the contract and move as work happens. The
        experimental definition -- code, data, split, metric, environment,
        statistics -- is what is pinned.
        """
        return self.canonical_dict(
            exclude={
                "status",
                "blockers",
                "notes",
                "control_run_id",
                "challenger_run_ids",
                "final_test_policy",
            }
        )

    def contract_hash(self) -> str:
        """Content identity of the experimental definition."""
        return hash_object(self.identity_dict())

    def blocker_fields(self) -> set[str]:
        return {blocker.field for blocker in self.blockers}

    def direction_of(self, metric: str) -> MetricDirection | None:
        return self.metric_direction.get(metric)

    def published_for(self, metric: str) -> PublishedScore | None:
        for score in self.published_score:
            if score.metric == metric:
                return score
        return None

    def all_metrics(self) -> list[str]:
        metrics = list(self.secondary_metrics)
        if self.primary_metric is not None:
            metrics.append(self.primary_metric)
        return sorted(set(metrics))

    @property
    def is_reproduced(self) -> bool:
        return self.status in REPRODUCED_OR_BEYOND


class ReproductionPlan(PramaanModel):
    """A complete, executable description of one reproduction attempt.

    Built without touching the network. A plan is data; running it is a separate
    act requiring an executor, and a plan for a blocked benchmark is still a
    useful artefact -- it says exactly what would be run once unblocked.
    """

    benchmark_id: str
    contract_hash: str
    contract_version: int

    official_commit: str | None
    data_version: str | None
    data_hash: str | None
    split_hash: str | None

    environment: SoftwareEnvironment
    hardware: HardwareRequirements
    command: tuple[str, ...]
    seeds: tuple[int, ...]

    expected_outputs: tuple[str, ...] = ()
    metric_parser: str | None = None
    timeout_seconds: int = Field(default=3600, ge=1)
    input_hashes: dict[str, str] = Field(default_factory=dict)
    output_root: str | None = None

    blocked: bool = False
    blockers: list[Blocker] = Field(default_factory=list)

    @model_validator(mode="after")
    def _blocked_plans_say_why(self) -> Self:
        if self.blocked and not self.blockers:
            raise ValueError("a blocked plan must name at least one blocker")
        return self

    def environment_hash(self) -> str:
        """Identity of the environment and hardware the plan demands."""
        return hash_object(
            {
                "environment": self.environment.canonical_dict(),
                "hardware": self.hardware.canonical_dict(),
            }
        )

    def plan_hash(self) -> str:
        return hash_object(self.canonical_dict(exclude={"blocked", "blockers"}))

    def run_id(self, seed: int) -> str:
        """Deterministic run identity, from immutable inputs only.

        Explicitly not from a clock: two machines running the same plan with the
        same seed must agree on the identifier, and re-running must not mint a
        fresh one that hides the collision with the first.
        """
        return stable_id(
            "brun",
            self.benchmark_id,
            self.contract_hash,
            self.official_commit,
            self.data_hash,
            self.split_hash,
            self.environment_hash(),
            list(self.command),
            seed,
        )


class PreparedEnvironment(PramaanModel):
    """What an executor produced from a plan, before anything ran."""

    plan_hash: str
    environment_hash: str
    workspace: str
    image_digest: str | None = None
    resolved_command: tuple[str, ...] = ()
    prepared_input_hashes: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class RawRunResult(PramaanModel):
    """The unparsed outcome of one execution."""

    plan_hash: str
    seed: int
    exit_code: int
    stdout_hash: str
    stderr_hash: str
    raw_output_hashes: dict[str, str] = Field(default_factory=dict)
    started_at: UtcDatetime
    finished_at: UtcDatetime
    duration_seconds: float = Field(ge=0.0)
    gpu_hours: float = Field(default=0.0, ge=0.0)
    cpu_hours: float = Field(default=0.0, ge=0.0)
    peak_memory_gb: float = Field(default=0.0, ge=0.0)
    energy_estimate_kwh: float | None = Field(default=None, ge=0.0)
    energy_estimate_method: str | None = None
    hardware_description: str | None = None
    driver_version: str | None = None
    cuda_version: str | None = None

    @model_validator(mode="after")
    def _time_moves_forward(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("run finished before it started")
        return self


class ReproductionRun(VersionedModel):
    """The immutable manifest of one run. This is the unit reports are built on.

    A run that failed is as much a record as one that succeeded, and stays in the
    registry. A benchmark whose failures can be dropped is a benchmark whose
    reported score is the maximum over attempts.
    """

    run_id: str
    benchmark_id: str
    contract_hash: str
    contract_version: int

    official_commit: str | None
    dataset_hash: str | None
    split_hash: str | None
    environment_hash: str
    metric_code_hash: str | None
    package_lock_hash: str | None

    command: tuple[str, ...]
    seed: int

    started_at: UtcDatetime
    finished_at: UtcDatetime
    duration_seconds: float = Field(ge=0.0)

    hardware_description: str | None = None
    driver_version: str | None = None
    cuda_version: str | None = None

    stdout_hash: str
    stderr_hash: str
    raw_output_hashes: dict[str, str] = Field(default_factory=dict)
    artefact_hashes: dict[str, str] = Field(default_factory=dict)

    parsed_metrics: dict[str, float] = Field(default_factory=dict)
    per_unit_scores: dict[str, list[float]] = Field(default_factory=dict)
    unit_ids: list[str] = Field(default_factory=list)

    gpu_hours: float = Field(default=0.0, ge=0.0)
    cpu_hours: float = Field(default=0.0, ge=0.0)
    peak_memory_gb: float = Field(default=0.0, ge=0.0)
    energy_estimate_kwh: float | None = Field(default=None, ge=0.0)
    energy_estimate_method: str | None = None

    exit_status: int
    failure_classification: FailureClass = FailureClass.NONE
    role: str = "control"
    """``control`` reproduces the published model; ``challenger`` competes with it."""

    reads_test_period: bool = False
    test_access_authorisation: str | None = None
    is_rerun_of: str | None = None
    post_test_changes: list[str] = Field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.exit_status == 0 and self.failure_classification is FailureClass.NONE

    def unit_set_hash(self) -> str:
        """Identity of the evaluation units, so two runs can be shown comparable."""
        return hash_object(sorted(self.unit_ids))

    def manifest_hash(self) -> str:
        return hash_object(self.canonical_dict())


class ToleranceCheck(PramaanModel):
    """One published metric, next to what a run actually produced.

    ``observed`` and ``delta`` are ``None`` when the run produced no value for
    the metric at all. That is a different fact from "produced 0.0", and
    collapsing the two would let a metric the parser silently dropped be read as
    a score of zero -- or, for a lower-is-better metric, as a perfect one.
    """

    metric: str
    published: float
    observed: float | None
    delta: float | None
    within_tolerance: bool
    tolerance: Tolerance | None = None
    note: str | None = None


class ComparisonResult(VersionedModel):
    """Whether a challenger may be described as having exceeded a control.

    Every gate is recorded with its own verdict. A comparison that says
    ``exceeded=False`` has to be able to say which gate refused, or the refusal
    is not reviewable.
    """

    benchmark_id: str
    contract_hash: str
    control_run_id: str
    challenger_run_ids: list[str]
    primary_metric: str
    metric_direction: MetricDirection

    control_score: float | None = None
    challenger_score: float | None = None
    improvement: float | None = None
    effect_size: float | None = None

    confidence_interval: tuple[float, float] | None = None
    confidence_alpha: float | None = None
    p_value: float | None = None
    seed_count: int = 0

    gates: dict[str, bool] = Field(default_factory=dict)
    gate_details: list[str] = Field(default_factory=list)
    secondary_checks: list[ToleranceCheck] = Field(default_factory=list)

    verdict: BenchmarkStatus = BenchmarkStatus.CHALLENGED_NOT_EXCEEDED

    @property
    def exceeded(self) -> bool:
        return self.verdict is BenchmarkStatus.EXCEEDED

    def failed_gates(self) -> list[str]:
        return sorted(name for name, passed in self.gates.items() if not passed)
