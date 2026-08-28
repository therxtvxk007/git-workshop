import { Rng, fakeHash } from "./rng";
import { MOCK_DISTRICTS } from "./districts";
import type {
  BacktestRun,
  ContributionReport,
  DataHealth,
  EventFamily,
  EvidenceItem,
  ForecastDetail,
  ForecastStatus,
  HistoryPoint,
  Interval,
  Metric,
  ModelArtifact,
  ObservedOutcome,
  ReviewTaskSummary,
  RunLineage,
  SnapshotInfo,
} from "@/lib/api/types";

/**
 * The deterministic demo world.
 *
 * Built once, from a fixed seed, at module load. Two properties are
 * load-bearing:
 *
 *  1. **Every record carries `is_demo: true`.** Not a UI flag — a field on the
 *     data. Export, print and the safety banner all read it, so a spreadsheet
 *     that escapes this console still says what it is.
 *  2. **Every state the UI can render is reachable.** All five forecast
 *     statuses, a syndicated evidence cluster, a permission-restricted item, a
 *     post-cutoff item, a source outage, an under-covered district, a disputed
 *     review task and a right-censored backtest fold all exist on purpose, so
 *     "I could not reproduce that empty state" is never the answer.
 */

export const MOCK_CUTOFF = "2026-01-15T00:00:00Z";
const SNAPSHOT_BUILT = "2026-01-15T00:12:00Z";
const CREATED_AT = "2026-01-15T02:40:00Z";
const SNAPSHOT_HASH = fakeHash("sha256", "snapshot", MOCK_CUTOFF);
const RUN_ID = "run_2026-01-15_e2e_v1";

const EVENT_FAMILIES: EventFamily[] = [
  "civil_unrest",
  "flood",
  "drought",
  "epidemic_signal",
  "infrastructure_disruption",
  "displacement",
];

export const EVENT_FAMILY_LABELS: Record<EventFamily, string> = {
  civil_unrest: "Civil unrest",
  flood: "Flood",
  drought: "Drought",
  epidemic_signal: "Epidemic signal",
  infrastructure_disruption: "Infrastructure disruption",
  displacement: "Displacement",
};

const SOURCES = [
  { id: "gdelt", name: "GDELT 2.0", license: "GDELT terms of use" },
  { id: "reliefweb", name: "ReliefWeb", license: "ReliefWeb API terms (appname required)" },
  { id: "data_gov_in", name: "data.gov.in", license: "Government Open Data Licence — India" },
  { id: "acled", name: "ACLED", license: "ACLED licence — attribution required, redistribution restricted" },
] as const;

const STATUS_CYCLE: ForecastStatus[] = [
  "watch",
  "monitor",
  "alert",
  "monitor",
  "insufficient_evidence",
  "watch",
  "abstain",
  "monitor",
];

function iso(base: string, deltaMs: number): string {
  return new Date(Date.parse(base) + deltaMs).toISOString().replace(".000Z", "Z");
}

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

function makeInterval(point: number, width: number, rng: Rng): Interval {
  const jitter = rng.float(0.8, 1.2);
  const half = Math.min(width * jitter, 0.45);
  return {
    lower: Math.max(0, Number((point - half).toFixed(4))),
    upper: Math.min(1, Number((point + half * 1.15).toFixed(4))),
    coverage: 0.9,
    method: "split_conformal@v0",
  };
}

/* ---------------------------------------------------------------- evidence */

const CLAIM_TEMPLATES: Record<EventFamily, string[]> = {
  civil_unrest: [
    "Trade unions announced an indefinite strike beginning next week in {district}.",
    "District administration imposed prohibitory orders around the {district} secretariat.",
    "A protest march in {district} drew several thousand participants, police said.",
  ],
  flood: [
    "The {district} river gauge crossed its first warning level on Tuesday.",
    "IMD issued an orange rainfall warning covering {district} for 48 hours.",
    "Relief camps opened in three blocks of {district} after overnight rain.",
  ],
  drought: [
    "Cumulative rainfall in {district} is 41% below the long-period average.",
    "Reservoir storage serving {district} fell to 18% of live capacity.",
    "Sowing in {district} is delayed across the kharif season, officials said.",
  ],
  epidemic_signal: [
    "Fever-clinic attendance in {district} rose sharply over two weeks.",
    "The {district} health department reported a cluster of acute diarrhoeal cases.",
    "Vector-control drives were expanded to eleven wards of {district}.",
  ],
  infrastructure_disruption: [
    "Scheduled load-shedding was extended across {district} feeders.",
    "A transmission fault interrupted supply to parts of {district} for nine hours.",
    "Water supply in {district} was suspended for pipeline repair works.",
  ],
  displacement: [
    "Families from low-lying wards of {district} moved to temporary shelters.",
    "A rehabilitation survey began for households displaced in {district}.",
    "Shelter occupancy in {district} exceeded its assessed capacity.",
  ],
};

interface WorldForecast {
  detail: ForecastDetail;
  evidence: EvidenceItem[];
  contributions: ContributionReport;
  history: HistoryPoint[];
}

function buildEvidence(
  rng: Rng,
  forecastId: string,
  districtId: string,
  districtName: string,
  family: EventFamily,
  index: number,
): EvidenceItem[] {
  const count = rng.int(3, 6);
  const templates = CLAIM_TEMPLATES[family];
  const items: EvidenceItem[] = [];
  // Every eighth forecast gets a syndication cluster: one original and two
  // rewrites. It is the single most common way an evidence count overstates
  // how much independent information there actually is.
  const syndicated = index % 8 === 3;
  const clusterId = `clu_${forecastId.slice(-6)}`;

  for (let i = 0; i < count; i += 1) {
    const source = SOURCES[i % SOURCES.length]!;
    const claim = templates[i % templates.length]!.replace("{district}", districtName);
    const observedDelta = -rng.int(6, 26) * DAY + rng.int(0, 23) * HOUR;
    // One item per forecast lands after the cutoff. It is retained and
    // labelled rather than hidden, so an analyst can see what the model was
    // NOT allowed to use.
    const postCutoff = i === count - 1 && index % 5 === 2;
    const firstObserved = iso(MOCK_CUTOFF, postCutoff ? rng.int(4, 60) * HOUR : observedDelta);
    // ACLED redistribution is restricted, so the body is withheld at the API
    // rather than blurred in the UI.
    const restricted = source.id === "acled" && index % 6 === 1;
    const isRewrite = syndicated && i > 0 && i <= 2;

    items.push({
      evidence_id: `ev_${forecastId.slice(-8)}_${i}`,
      observation_id: `obs_${fakeHash("o", forecastId, i).slice(2, 14)}`,
      source_id: source.id,
      source_name: source.name,
      title: `${districtName}: ${EVENT_FAMILY_LABELS[family].toLowerCase()} reporting`,
      body: restricted
        ? null
        : `${claim} The district control room said monitoring would continue through the week. ` +
          `Officials did not confirm whether additional measures were planned.`,
      claim,
      stance: i === 0 ? "supports" : rng.pick(["supports", "supports", "context", "contradicts"]),
      modality: rng.pick(["asserted", "planned", "possible", "unknown"]),
      reliability: Number(rng.float(0.35, 0.95).toFixed(3)),
      independence_cluster: syndicated && i <= 2 ? clusterId : null,
      cluster_size: syndicated && i <= 2 ? 3 : 1,
      syndication_of: isRewrite ? `ev_${forecastId.slice(-8)}_0` : null,
      published_at: iso(firstObserved, -rng.int(1, 8) * HOUR),
      first_observed_at: firstObserved,
      retrieved_at: iso(firstObserved, rng.int(1, 5) * HOUR),
      url: restricted ? null : `https://example.invalid/${source.id}/${forecastId.slice(-8)}-${i}`,
      span_start: 0,
      span_end: claim.length,
      district_ids: [districtId],
      event_family: family,
      access: restricted ? "restricted" : isRewrite ? "syndicated" : "open",
      license: source.license,
      post_cutoff: postCutoff,
      is_demo: true,
    });
  }
  return items;
}

function buildContributions(
  rng: Rng,
  forecastId: string,
  probability: number,
): ContributionReport {
  const baseline = Math.log(0.08 / 0.92);
  const groups = [
    {
      group: "evidence",
      label: "Evidence",
      members: [
        ["evidence.support_weight", "Weighted supporting claims", "Reliability-weighted count of supporting evidence."],
        ["evidence.contradiction_weight", "Contradicting claims", "Explicit denials and contradicting reports."],
        ["evidence.independent_clusters", "Independent clusters", "Distinct sources after de-syndication."],
      ],
    },
    {
      group: "base_rate",
      label: "Base rate & seasonality",
      members: [
        ["base_rate.district_12m", "District 12-month rate", "Historical frequency in this district."],
        ["base_rate.seasonal_index", "Seasonal index", "Month-of-year multiplier for this family."],
      ],
    },
    {
      group: "recency",
      label: "Recency & momentum",
      members: [
        ["recency.claims_7d", "Claims in trailing 7 days", "Volume of new mentions inside the activity window."],
        ["recency.slope_28d", "28-day slope", "Direction of mention volume over four weeks."],
      ],
    },
    {
      group: "coverage",
      label: "Coverage & data quality",
      members: [
        ["coverage.document_density", "Document density", "How well this district is covered at all."],
        ["coverage.delay_penalty", "Ingestion delay penalty", "Downweights signals arriving late."],
      ],
    },
  ];

  // Contributions are drawn to sum, through the logistic, near the reported
  // probability. They are illustrative, not a re-derivation: the console must
  // never look like it recomputed the model.
  const target = Math.log(Math.max(probability, 1e-4) / Math.max(1 - probability, 1e-4));
  const raw = groups.map(() => rng.float(-1, 1.6));
  const scale = (target - baseline) / (raw.reduce((a, b) => a + b, 0) || 1);

  return {
    forecast_id: forecastId,
    baseline_log_odds: Number(baseline.toFixed(4)),
    method: "grouped_perturbation@v0",
    method_caveat:
      "Attribution shows how the model's score moves when a feature group is perturbed. " +
      "It is not a causal claim about the district, and groups are correlated, so " +
      "contributions do not partition the score cleanly.",
    groups: groups.map((g, gi) => {
      const total = Number((raw[gi]! * scale).toFixed(4));
      const shares = g.members.map(() => rng.float(0.2, 1));
      const shareSum = shares.reduce((a, b) => a + b, 0);
      return {
        group: g.group,
        label: g.label,
        contribution: total,
        members: g.members.map(([feature, label, description], mi) => ({
          feature: feature!,
          label: label!,
          contribution: Number(((total * shares[mi]!) / shareSum).toFixed(4)),
          value: Number(rng.float(0, 12).toFixed(2)),
          description: description!,
        })),
      };
    }),
  };
}

function buildHistory(
  rng: Rng,
  forecastId: string,
  districtId: string,
  family: EventFamily,
  finalProbability: number,
  status: ForecastStatus,
  outcome: ObservedOutcome | null,
): HistoryPoint[] {
  const points: HistoryPoint[] = [];
  const weeks = 12;
  let probability = Math.max(0.01, finalProbability - rng.float(0.05, 0.25));
  for (let w = weeks; w >= 0; w -= 1) {
    const cutoff = iso(MOCK_CUTOFF, -w * 7 * DAY);
    probability =
      w === 0
        ? finalProbability
        : Math.min(0.97, Math.max(0.005, probability + rng.float(-0.05, 0.07)));
    points.push({
      cutoff_at: cutoff,
      calibrated_probability: Number(probability.toFixed(4)),
      raw_probability: Number(probability.toFixed(4)),
      interval: makeInterval(probability, 0.09 + w * 0.004, rng),
      status: w === 0 ? status : probability > 0.45 ? "watch" : "monitor",
      forecast_id: w === 0 ? forecastId : `${forecastId}_h${w}`,
      // An outcome is attached only to folds old enough to be scoreable. A
      // right-censored non-event rendered as a miss is the classic way a
      // backtest flatters itself, and the trend chart must not repeat it.
      observed_outcome: w >= 6 ? outcome : null,
    });
  }
  void districtId;
  void family;
  return points;
}

/* --------------------------------------------------------------- forecasts */

function buildWorld() {
  const rng = new Rng(20260115);
  const forecasts: WorldForecast[] = [];

  MOCK_DISTRICTS.forEach((district, di) => {
    const familyCount = 2 + (di % 2);
    for (let f = 0; f < familyCount; f += 1) {
      const index = di * 3 + f;
      const family = EVENT_FAMILIES[(di + f * 2) % EVENT_FAMILIES.length]!;
      const status = STATUS_CYCLE[index % STATUS_CYCLE.length]!;

      const calibrated =
        status === "alert"
          ? rng.float(0.62, 0.88)
          : status === "watch"
            ? rng.float(0.34, 0.61)
            : status === "abstain"
              ? rng.float(0.2, 0.7)
              : status === "insufficient_evidence"
                ? rng.float(0.05, 0.3)
                : rng.float(0.04, 0.33);

      const forecastId = `fc_${fakeHash("f", district.district_id, family).slice(2, 18)}`;
      const evidenceCount =
        status === "insufficient_evidence" ? rng.int(0, 1) : rng.int(3, 6);
      const evidence =
        evidenceCount === 0
          ? []
          : buildEvidence(rng, forecastId, district.district_id, district.name, family, index);
      const clusters = new Set(
        evidence.map((e) => e.independence_cluster ?? e.observation_id),
      ).size;

      // Abstention is a model refusal, so it must not ship a confident
      // interval. Insufficient evidence has no interval at all.
      const interval =
        status === "insufficient_evidence"
          ? null
          : makeInterval(calibrated, status === "abstain" ? 0.3 : 0.1, rng);

      const scoreableFrom = iso(MOCK_CUTOFF, 45 * DAY);
      const outcome: ObservedOutcome | null =
        index % 4 === 0
          ? {
              occurred: rng.bool(calibrated),
              resolved_at: iso(MOCK_CUTOFF, 38 * DAY),
              scoreable_from: scoreableFrom,
              match_confidence: Number(rng.float(0.6, 0.98).toFixed(3)),
              note: null,
            }
          : null;

      const detail: ForecastDetail = {
        forecast_id: forecastId,
        district_id: district.district_id,
        district_name: district.name,
        state: district.state,
        event_family: family,
        cutoff_at: MOCK_CUTOFF,
        created_at: CREATED_AT,
        horizon_days: 30,
        // Identical to the calibrated value on purpose. This run records
        // calibration=identity@uncalibrated, which passes generator output
        // through unchanged -- so fixtures where the two differ would
        // contradict the provenance the same record carries.
        raw_probability: Number(calibrated.toFixed(4)),
        calibrated_probability: Number(calibrated.toFixed(4)),
        interval,
        epistemic_uncertainty: Number(
          (status === "abstain" ? rng.float(0.55, 0.9) : rng.float(0.05, 0.4)).toFixed(4),
        ),
        base_rate: Number(rng.float(0.02, 0.14).toFixed(4)),
        status,
        evidence_count: evidence.length,
        independent_cluster_count: clusters,
        snapshot_hash: SNAPSHOT_HASH,
        is_demo: true,
        hypothesis: {
          event_id: `ev_${fakeHash("e", forecastId).slice(2, 14)}`,
          event_type: family,
          actor_ids: [`act_${district.state_code.toLowerCase()}_admin`],
          target_ids: [`tgt_${district.district_id}`],
          location_cells: { [district.district_id]: 1 },
          time_bucket_probabilities: { "0-7d": 0.18, "8-14d": 0.27, "15-30d": 0.55 },
          severity_distribution: { low: 0.55, moderate: 0.34, high: 0.11 },
          generated_by: ["G0.base_rate", index % 3 === 0 ? "G1.cri_rules" : "G0.base_rate"],
          novelty_score: Number(rng.float(0, 0.7).toFixed(3)),
        },
        evidence: evidence.map((e) => ({
          evidence_id: e.evidence_id,
          observation_id: e.observation_id,
          span_start: e.span_start,
          span_end: e.span_end,
          claim: e.claim,
          stance: e.stance,
          independence_cluster: e.independence_cluster,
          reliability: e.reliability,
        })),
        provenance: {
          snapshot_hash: SNAPSHOT_HASH,
          run_id: RUN_ID,
          model_versions: {
            generator: "G0.base_rate@0.4.1",
            extractor: "rule_map@0.2.0",
            calibrator: "identity@uncalibrated",
            risk_controller: "fixed_threshold@placeholder",
          },
          calibration: "identity@uncalibrated",
          alert_policy: "fixed_threshold@placeholder",
          code_version: "pramaanx@0.4.1+cb34f9b",
          config_hash: fakeHash("cfg", "e2e_v1"),
          generated_by: ["G0.base_rate"],
          snapshot_built_at: SNAPSHOT_BUILT,
        },
        observed_outcome: outcome,
      };

      forecasts.push({
        detail,
        evidence,
        contributions: buildContributions(rng, forecastId, calibrated),
        history: buildHistory(
          rng,
          forecastId,
          district.district_id,
          family,
          calibrated,
          status,
          outcome,
        ),
      });
    }
  });

  return forecasts;
}

export const WORLD = buildWorld();

export const MOCK_SNAPSHOT: SnapshotInfo = {
  snapshot_hash: SNAPSHOT_HASH,
  cutoff_at: MOCK_CUTOFF,
  built_at: SNAPSHOT_BUILT,
  data_mode: "synthetic",
  event_families: EVENT_FAMILIES,
  engine_version: "pramaanx 0.4.1 (M0 + Phase 1 connectors, Phase 2 downstream)",
  schema_version: 2,
  calibration: "identity@uncalibrated",
  alert_policy: "fixed_threshold@placeholder",
  generators: ["G0.base_rate", "G1.cri_rules"],
};

/* -------------------------------------------------------------- review */

/**
 * Which forecast each task is about.
 *
 * Kept as an explicit map rather than recovered by slicing the task id back
 * into a forecast id. The first version of this file did the latter, the two
 * slice lengths disagreed by four characters, and every task detail request
 * failed -- an id is an opaque handle, and reconstructing one from another is
 * a join waiting to break.
 */
export const MOCK_TASK_FORECASTS: Record<string, string> = {};

export const MOCK_REVIEW_TASKS: ReviewTaskSummary[] = WORLD.slice(0, 14).map((w, i) => ({
  task_id: `task_${w.detail.forecast_id.slice(3, 15)}`,
  event_family: w.detail.event_family,
  district_name: w.detail.district_name,
  state: w.detail.state,
  // The queue deliberately contains a disputed task and an adjudicated one, so
  // the escalation path is demonstrable without hand-editing fixtures.
  task_state:
    i === 2 ? "disputed" : i === 3 ? "adjudicated" : i === 4 ? "submitted" : i < 7 ? "in_review" : "pending",
  assigned_at: iso(MOCK_CUTOFF, -(i + 1) * 6 * HOUR),
  due_at: iso(MOCK_CUTOFF, (7 - i) * DAY),
  reviews_submitted: i === 2 || i === 3 ? 2 : i === 4 ? 1 : 0,
  own_review_submitted: i === 3 || i === 4,
}));

for (const [index, task] of MOCK_REVIEW_TASKS.entries()) {
  MOCK_TASK_FORECASTS[task.task_id] = WORLD[index]!.detail.forecast_id;
}

/* ------------------------------------------------------------ backtests */

function metric(
  key: string,
  label: string,
  value: number | null,
  lowerIsBetter: boolean,
  unit: Metric["unit"],
  description: string,
  ci: [number, number] | null = null,
): Metric {
  return { key, label, value, ci, lower_is_better: lowerIsBetter, unit, description };
}

function buildRun(
  runId: string,
  label: string,
  seed: number,
  quality: number,
  excludedFolds: number,
): BacktestRun {
  const rng = new Rng(seed);
  const reliability = Array.from({ length: 10 }, (_, i) => {
    const lower = i / 10;
    const meanPredicted = lower + 0.05;
    // A well-behaved but visibly imperfect diagram: over-confident in the
    // upper bins, which is what an uncalibrated identity mapping looks like.
    const observed = Math.min(
      1,
      Math.max(0, meanPredicted * quality + rng.float(-0.06, 0.06) + (1 - quality) * 0.03),
    );
    return {
      bin_lower: lower,
      bin_upper: lower + 0.1,
      mean_predicted: Number(meanPredicted.toFixed(4)),
      observed_frequency: Number(observed.toFixed(4)),
      count: Math.max(4, Math.round(420 * Math.exp(-3.1 * lower)) + rng.int(-8, 8)),
    };
  });

  const prCurve = Array.from({ length: 21 }, (_, i) => {
    const recall = i / 20;
    const precision = Math.min(
      1,
      Math.max(0.03, (0.62 * quality) / (1 + 2.4 * recall) + rng.float(-0.02, 0.02)),
    );
    return { x: Number(recall.toFixed(3)), y: Number(precision.toFixed(4)), label: null };
  });

  const budgetRecall = Array.from({ length: 16 }, (_, i) => {
    const budget = i * 10;
    return {
      x: budget,
      y: Number(Math.min(1, 1 - Math.exp((-budget / 62) * quality)).toFixed(4)),
      label: `${budget} alerts / week`,
    };
  });

  const abstentionRisk = Array.from({ length: 11 }, (_, i) => {
    const abstained = i / 20;
    return {
      x: Number(abstained.toFixed(3)),
      y: Number(Math.max(0.02, 0.24 - abstained * 0.32 * quality).toFixed(4)),
      label: null,
    };
  });

  const ece = Number(
    (
      reliability.reduce(
        (acc, b) => acc + (b.count * Math.abs(b.mean_predicted - b.observed_frequency)),
        0,
      ) / reliability.reduce((acc, b) => acc + b.count, 0)
    ).toFixed(4),
  );

  return {
    run_id: runId,
    label,
    experiment: "configs/experiments/e2e_v1.yaml",
    created_at: iso(MOCK_CUTOFF, -seed % 9 * DAY),
    snapshot_hash: fakeHash("sha256", "snapshot", runId),
    fold_count: 26,
    first_cutoff: "2025-07-16T00:00:00Z",
    last_cutoff: "2026-01-15T00:00:00Z",
    event_families: EVENT_FAMILIES.slice(0, 4),
    excluded_folds: excludedFolds,
    is_demo: true,
    sample_size: 4820,
    positive_rate: 0.0731,
    metrics: [
      metric("brier", "Brier score", Number((0.061 / quality).toFixed(4)), true, "probability",
        "Mean squared error of the probability. Lower is better; the base rate alone scores 0.068.",
        [Number((0.055 / quality).toFixed(4)), Number((0.068 / quality).toFixed(4))]),
      metric("log_loss", "Log loss", Number((0.244 / quality).toFixed(4)), true, "logloss",
        "Negative log likelihood. Punishes confident mistakes hardest."),
      metric("ece", "Expected calibration error", ece, true, "probability",
        "Count-weighted gap between predicted and observed frequency across ten bins."),
      metric("auc_pr", "AUC-PR", Number((0.29 * quality).toFixed(4)), false, "ratio",
        "Area under the precision-recall curve. The 7.3% positive rate is the no-skill floor.",
        [Number((0.24 * quality).toFixed(4)), Number((0.34 * quality).toFixed(4))]),
      metric("alert_precision", "Alert precision", Number((0.41 * quality).toFixed(4)), false, "ratio",
        "Share of ALERT statuses whose event was observed within the horizon."),
      metric("alert_recall", "Alert recall", Number((0.22 * quality).toFixed(4)), false, "ratio",
        "Share of observed events that carried an ALERT at the preceding cutoff."),
      metric("abstention_rate", "Abstention rate", 0.084, true, "ratio",
        "Share of candidates the risk controller refused to score."),
      metric("coverage_90", "Interval coverage (90%)", Number((0.9 * quality).toFixed(4)), false, "probability",
        "Empirical coverage of the nominal 90% interval. Below 0.9 means the intervals are too tight."),
      metric("miss_rate_guarantee", "Conformal miss-rate guarantee", null, true, "ratio",
        "Not computed: this run used the placeholder alert policy, which carries no guarantee."),
    ],
    reliability,
    pr_curve: prCurve,
    budget_recall: budgetRecall,
    abstention_risk: abstentionRisk,
    arms: [
      {
        arm_id: "base_rate",
        label: "G0 base rate only",
        description: "Historical district frequency with a seasonal index. The floor any model must beat.",
        metrics: [
          metric("brier", "Brier score", 0.0684, true, "probability", "Base-rate reference."),
          metric("auc_pr", "AUC-PR", 0.0731, false, "ratio", "Equals the positive rate by construction."),
        ],
      },
      {
        arm_id: "evidence_weighted",
        label: "G0 + evidence weighting",
        description: "Adds reliability-weighted, de-syndicated evidence counts.",
        metrics: [
          metric("brier", "Brier score", Number((0.061 / quality).toFixed(4)), true, "probability", "This run's headline arm."),
          metric("auc_pr", "AUC-PR", Number((0.29 * quality).toFixed(4)), false, "ratio", "Above the no-skill floor."),
        ],
      },
      {
        arm_id: "evidence_weighted_calibrated",
        label: "+ isotonic calibration",
        description: "Post-hoc isotonic calibration fitted on earlier folds only.",
        metrics: [
          metric("brier", "Brier score", Number((0.0578 / quality).toFixed(4)), true, "probability", "Calibration helps the score without changing the ranking."),
          metric("auc_pr", "AUC-PR", Number((0.29 * quality).toFixed(4)), false, "ratio", "Unchanged: calibration is monotone."),
        ],
      },
    ],
  };
}

export const MOCK_RUNS: BacktestRun[] = [
  buildRun(RUN_ID, "e2e_v1 — 26 weekly folds", 20260115, 1, 2),
  buildRun("run_2025-12-18_e2e_v1", "e2e_v1 — previous release", 20251218, 0.88, 3),
  buildRun("run_2025-11-20_ablation", "Ablation: no ACLED", 20251120, 0.79, 5),
];

/* ----------------------------------------------------------- data health */

export const MOCK_DATA_HEALTH: DataHealth = {
  generated_at: SNAPSHOT_BUILT,
  snapshot_hash: SNAPSHOT_HASH,
  sources: [
    {
      source_id: "gdelt",
      name: "GDELT 2.0",
      status: "healthy",
      coverage: 0.94,
      districts_covered: 38,
      median_delay_hours: 0.4,
      p90_delay_hours: 2.1,
      last_document_at: iso(MOCK_CUTOFF, -25 * 60000),
      outages: [],
    },
    {
      source_id: "reliefweb",
      name: "ReliefWeb",
      status: "degraded",
      coverage: 0.61,
      districts_covered: 24,
      median_delay_hours: 9.5,
      p90_delay_hours: 46,
      last_document_at: iso(MOCK_CUTOFF, -14 * HOUR),
      outages: [
        {
          from: iso(MOCK_CUTOFF, -9 * DAY),
          to: iso(MOCK_CUTOFF, -8 * DAY),
          reason: "Appname rate limit exceeded; ingestion paused rather than retried unattended.",
        },
      ],
    },
    {
      source_id: "data_gov_in",
      name: "data.gov.in",
      status: "outage",
      coverage: 0.22,
      districts_covered: 9,
      median_delay_hours: null,
      p90_delay_hours: null,
      last_document_at: iso(MOCK_CUTOFF, -6 * DAY),
      outages: [
        {
          from: iso(MOCK_CUTOFF, -6 * DAY),
          to: null,
          reason: "Resource endpoint returning HTTP 500. Absence of signal here means nothing.",
        },
      ],
    },
    {
      source_id: "acled",
      name: "ACLED",
      status: "healthy",
      coverage: 0.88,
      districts_covered: 36,
      median_delay_hours: 72,
      p90_delay_hours: 168,
      last_document_at: iso(MOCK_CUTOFF, -3 * DAY),
      outages: [],
    },
  ],
  districts: MOCK_DISTRICTS.map((d, i) => {
    const coverage = i % 9 === 4 ? 0.12 + (i % 3) * 0.02 : 0.55 + ((i * 7) % 40) / 100;
    return {
      district_id: d.district_id,
      district_name: d.name,
      state: d.state,
      documents_30d: Math.round(coverage * 240),
      coverage: Number(Math.min(0.99, coverage).toFixed(3)),
      under_covered: coverage < 0.3,
    };
  }),
};

/* --------------------------------------------------------------- models */

export const MOCK_ARTIFACTS: ModelArtifact[] = [
  {
    artifact_id: "art_g0_base_rate_041",
    name: "G0 base-rate generator",
    kind: "generator",
    version: "0.4.1",
    trained_at: "2026-01-08T11:02:00Z",
    training_snapshot_hash: fakeHash("sha256", "snapshot", "2026-01-08"),
    code_version: "pramaanx@0.4.1+cb34f9b",
    config_hash: fakeHash("cfg", "g0"),
    parent_artifact_ids: [],
    metrics: [
      metric("brier", "Brier score", 0.0684, true, "probability", "On the 26-fold rolling backtest."),
    ],
    limitations:
      "Frequency and seasonality only. It cannot react to a novel situation, and it will " +
      "assign a low probability to any event type this district has not seen before.",
  },
  {
    artifact_id: "art_g1_cri_rules_020",
    name: "G1 CRI rule generator",
    kind: "generator",
    version: "0.2.0",
    trained_at: null,
    training_snapshot_hash: null,
    code_version: "pramaanx@0.4.1+cb34f9b",
    config_hash: fakeHash("cfg", "g1"),
    parent_artifact_ids: [],
    metrics: [],
    limitations:
      "Hand-written rules, not learned. Recall is bounded by the rule set, and rules were " +
      "authored against Tier 0 sources only.",
  },
  {
    artifact_id: "art_calibrator_identity",
    name: "Identity calibrator (placeholder)",
    kind: "calibrator",
    version: "uncalibrated",
    trained_at: null,
    training_snapshot_hash: null,
    code_version: "pramaanx@0.4.1+cb34f9b",
    config_hash: fakeHash("cfg", "cal"),
    parent_artifact_ids: ["art_g0_base_rate_041"],
    metrics: [metric("ece", "Expected calibration error", 0.0712, true, "probability", "Uncalibrated by construction.")],
    limitations:
      "This is not a calibrator. It passes raw generator output through unchanged, and every " +
      "forecast records calibration=identity@uncalibrated so the number cannot be misread as calibrated.",
  },
  {
    artifact_id: "art_risk_fixed_threshold",
    name: "Fixed-threshold risk controller (placeholder)",
    kind: "risk_controller",
    version: "placeholder",
    trained_at: null,
    training_snapshot_hash: null,
    code_version: "pramaanx@0.4.1+cb34f9b",
    config_hash: fakeHash("cfg", "risk"),
    parent_artifact_ids: ["art_calibrator_identity"],
    metrics: [],
    limitations:
      "Statuses come from fixed thresholds. There is no conformal miss-rate guarantee, and the " +
      "miss-versus-false-alert trade-off is a human decision nobody has made yet.",
  },
  {
    artifact_id: "art_extractor_rule_map",
    name: "Deterministic extraction map",
    kind: "extractor",
    version: "0.2.0",
    trained_at: null,
    training_snapshot_hash: null,
    code_version: "pramaanx@0.4.1+cb34f9b",
    config_hash: fakeHash("cfg", "ext"),
    parent_artifact_ids: [],
    metrics: [],
    limitations: "Only handles sources that are already coded. Free-text sources fall through unextracted.",
  },
];

export const MOCK_LINEAGE: Record<string, RunLineage> = Object.fromEntries(
  MOCK_RUNS.map((run) => [
    run.run_id,
    {
      run_id: run.run_id,
      nodes: [
        { id: "dataset_bronze", label: "Bronze ingest", kind: "dataset" as const, at: iso(run.created_at, -2 * DAY) },
        { id: run.snapshot_hash, label: `Snapshot ${run.snapshot_hash.slice(7, 15)}`, kind: "snapshot" as const, at: iso(run.created_at, -1 * DAY) },
        { id: run.run_id, label: run.label, kind: "run" as const, at: run.created_at },
        { id: "art_g0_base_rate_041", label: "G0 base-rate generator", kind: "artifact" as const, at: "2026-01-08T11:02:00Z" },
        { id: "art_calibrator_identity", label: "Identity calibrator", kind: "artifact" as const, at: null },
        { id: "art_risk_fixed_threshold", label: "Fixed-threshold controller", kind: "artifact" as const, at: null },
      ],
      edges: [
        { from: "dataset_bronze", to: run.snapshot_hash, label: "cutoff-filtered" },
        { from: run.snapshot_hash, to: run.run_id, label: "scored" },
        { from: "art_g0_base_rate_041", to: run.run_id, label: "generator" },
        { from: "art_calibrator_identity", to: run.run_id, label: "calibrator" },
        { from: "art_risk_fixed_threshold", to: run.run_id, label: "risk policy" },
      ],
    },
  ]),
);
