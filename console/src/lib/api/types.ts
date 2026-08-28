import { z } from "zod";

/**
 * The wire contract between this console and the Pramaan-X engine.
 *
 * Field names mirror `src/pramaanx/schemas/` in this repository exactly, so a
 * reader can diff the two by eye. Where the console needs something the engine
 * record does not carry (a district projection, a probability interval, a
 * presentation label) the field is marked CONSOLE-LAYER below and documented in
 * docs/API_INTEGRATION.md as part of the serving API rather than the record.
 *
 * Everything is validated. An unvalidated response is an invitation to render a
 * probability of 1.4 as "140% likely", and this console would rather show an
 * error than a number it cannot vouch for.
 */

/* ------------------------------------------------------------------ atoms */

/** Engine: `pramaanx.schemas.base.Probability`. */
export const probabilitySchema = z
  .number({ invalid_type_error: "probability must be a number" })
  .min(0, "probability below 0")
  .max(1, "probability above 1");

/** Engine: `pramaanx.schemas.base.UtcDatetime`. Naive timestamps are rejected. */
export const utcDatetimeSchema = z
  .string()
  .refine((value) => !Number.isNaN(Date.parse(value)), "not a parseable timestamp")
  .refine(
    (value) => /(?:Z|[+-]\d{2}:?\d{2})$/.test(value.trim()),
    "timestamp has no timezone offset; a guessed timezone is a cutoff bug",
  );

/** A snapshot hash is what makes a forecast auditable, so it may not be blank. */
export const snapshotHashSchema = z
  .string()
  .trim()
  .min(1, "forecast requires a snapshot_hash");

/**
 * A two-sided uncertainty interval. CONSOLE-LAYER.
 *
 * One-sided intervals are rejected rather than defaulted: an interval whose
 * upper bound was silently filled in with the point estimate looks tight and
 * confident, which is the opposite of what a missing bound means.
 */
export const intervalSchema = z
  .object({
    lower: probabilitySchema,
    upper: probabilitySchema,
    /** Nominal coverage, e.g. 0.9 for a 90% interval. */
    coverage: probabilitySchema,
    method: z.string().min(1),
  })
  .refine((i) => i.lower <= i.upper, "interval lower bound exceeds upper bound");

export const eventFamilySchema = z.enum([
  "civil_unrest",
  "flood",
  "drought",
  "epidemic_signal",
  "infrastructure_disruption",
  "displacement",
]);

/** Engine: `pramaanx.schemas.forecast.ForecastStatus`. */
export const forecastStatusSchema = z.enum([
  "alert",
  "watch",
  "monitor",
  "abstain",
  "insufficient_evidence",
]);

/** Engine: `ACTIONABLE_STATUSES`. */
export const ACTIONABLE_STATUSES: readonly ForecastStatus[] = ["alert", "watch"];
/** Engine: `RETAINED_STATUSES` — `abstain` is deliberately absent. */
export const RETAINED_STATUSES: readonly ForecastStatus[] = [
  "alert",
  "watch",
  "monitor",
  "insufficient_evidence",
];

/** Engine: `pramaanx.schemas.evidence.Stance`. */
export const stanceSchema = z.enum(["supports", "contradicts", "context"]);

/** Engine: `pramaanx.schemas.event.EventModality`. */
export const modalitySchema = z.enum([
  "asserted",
  "planned",
  "possible",
  "denied",
  "unknown",
]);

/**
 * Engine: `normalised_distribution`. An empty map means "no opinion" and is
 * allowed; a non-empty one must sum to 1, because a distribution that quietly
 * sums to 0.6 becomes a silently deflated probability three stages later.
 */
export const distributionSchema = z
  .record(z.string(), z.number().min(0))
  .refine((d) => {
    const values = Object.values(d);
    if (values.length === 0) return true;
    return Math.abs(values.reduce((a, b) => a + b, 0) - 1) <= 1e-6;
  }, "distribution must sum to 1.0");

/* -------------------------------------------------------------- snapshot */

export const dataModeSchema = z.enum(["live", "synthetic"]);

export const snapshotInfoSchema = z.object({
  snapshot_hash: snapshotHashSchema,
  cutoff_at: utcDatetimeSchema,
  built_at: utcDatetimeSchema,
  /** `live` unlocks nothing; it only changes the banner and the export header. */
  data_mode: dataModeSchema,
  event_families: z.array(eventFamilySchema).min(1),
  engine_version: z.string().min(1),
  schema_version: z.number().int().positive(),
  /** e.g. `identity@uncalibrated` while calibration is a placeholder. */
  calibration: z.string().min(1),
  /** e.g. `fixed_threshold@placeholder`. */
  alert_policy: z.string().min(1),
  generators: z.array(z.string()),
});

/* -------------------------------------------------------------- district */

export const districtSchema = z.object({
  /** LGD district code. */
  district_id: z.string().min(1),
  name: z.string().min(1),
  state: z.string().min(1),
  state_code: z.string().min(1),
  centroid: z.object({ lat: z.number().min(-90).max(90), lon: z.number().min(-180).max(180) }),
  population: z.number().int().nonnegative().nullable(),
  is_demo: z.boolean(),
});

/* -------------------------------------------------------------- forecast */

const forecastSummaryBase = z.object({
  forecast_id: z.string().min(1),
  /** CONSOLE-LAYER: the district projection of `hypothesis.location_cells`. */
  district_id: z.string().min(1),
  district_name: z.string().min(1),
  state: z.string().min(1),
  event_family: eventFamilySchema,
  cutoff_at: utcDatetimeSchema,
  created_at: utcDatetimeSchema,
  horizon_days: z.number().int().positive(),
  raw_probability: probabilitySchema,
  calibrated_probability: probabilitySchema,
  /** CONSOLE-LAYER. Null when the engine ran with no interval method. */
  interval: intervalSchema.nullable(),
  epistemic_uncertainty: probabilitySchema,
  /** CONSOLE-LAYER: the base rate the probability should be read against. */
  base_rate: probabilitySchema.nullable(),
  status: forecastStatusSchema,
  evidence_count: z.number().int().nonnegative(),
  /** Ten outlets rewriting one wire story are one cluster, not ten. */
  independent_cluster_count: z.number().int().nonnegative(),
  snapshot_hash: snapshotHashSchema,
  is_demo: z.boolean(),
});

/**
 * The two cross-field rules the engine enforces on every record.
 *
 * Written as a `superRefine` callback rather than a generic wrapper: a helper
 * of the form `<T extends z.ZodTypeAny>(schema: T) => schema.refine(...)`
 * type-checks happily and then collapses the inferred output to `any`, which
 * disables every downstream field check without producing a single error. The
 * callback keeps `forecastSummaryBase`'s inferred shape intact on both schemas.
 */
function checkForecastInvariants(
  value: z.infer<typeof forecastSummaryBase>,
  ctx: z.RefinementCtx,
): void {
  if (Date.parse(value.created_at) < Date.parse(value.cutoff_at)) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["created_at"],
      message: "created_at precedes cutoff_at",
    });
  }
  if (value.independent_cluster_count > value.evidence_count) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["independent_cluster_count"],
      message: "independent clusters cannot outnumber evidence items",
    });
  }
}

export const forecastSummarySchema = forecastSummaryBase.superRefine(checkForecastInvariants);

export const evidenceRefSchema = z.object({
  observation_id: z.string().min(1),
  evidence_id: z.string().min(1),
  span_start: z.number().int().nonnegative().nullable(),
  span_end: z.number().int().nonnegative().nullable(),
  claim: z.string(),
  stance: stanceSchema,
  independence_cluster: z.string().nullable(),
  reliability: probabilitySchema,
});

export const hypothesisSchema = z.object({
  event_id: z.string().min(1),
  event_type: z.string().min(1),
  actor_ids: z.array(z.string()),
  target_ids: z.array(z.string()),
  location_cells: distributionSchema,
  time_bucket_probabilities: distributionSchema,
  severity_distribution: distributionSchema,
  generated_by: z.array(z.string()),
  novelty_score: probabilitySchema,
});

export const provenanceSchema = z.object({
  snapshot_hash: snapshotHashSchema,
  run_id: z.string().min(1),
  /** Engine: `ForecastRecord.model_versions`. */
  model_versions: z.record(z.string(), z.string()),
  calibration: z.string().min(1),
  alert_policy: z.string().min(1),
  code_version: z.string().min(1),
  config_hash: z.string().min(1),
  generated_by: z.array(z.string()),
  snapshot_built_at: utcDatetimeSchema,
});

/**
 * An outcome the console is allowed to show. `resolved_at` gates display: a
 * resolution is only rendered once it is past both the horizon end and the
 * reporting delay, otherwise a right-censored non-event reads as a miss.
 */
export const observedOutcomeSchema = z.object({
  occurred: z.boolean(),
  resolved_at: utcDatetimeSchema,
  /** When the outcome became safely scoreable. */
  scoreable_from: utcDatetimeSchema,
  match_confidence: probabilitySchema,
  note: z.string().nullable(),
});

export const forecastDetailSchema = forecastSummaryBase
  .extend({
    hypothesis: hypothesisSchema,
    evidence: z.array(evidenceRefSchema),
    provenance: provenanceSchema,
    observed_outcome: observedOutcomeSchema.nullable(),
  })
  .superRefine(checkForecastInvariants);

export const historyPointSchema = z.object({
  cutoff_at: utcDatetimeSchema,
  calibrated_probability: probabilitySchema,
  raw_probability: probabilitySchema,
  interval: intervalSchema.nullable(),
  status: forecastStatusSchema,
  forecast_id: z.string().min(1),
  observed_outcome: observedOutcomeSchema.nullable(),
});

/* ---------------------------------------------------------- contributions */

export const contributionMemberSchema = z.object({
  feature: z.string().min(1),
  label: z.string().min(1),
  /** Signed, in log-odds. Positive pushes the probability up. */
  contribution: z.number(),
  value: z.union([z.number(), z.string(), z.null()]),
  description: z.string(),
});

export const contributionGroupSchema = z.object({
  group: z.string().min(1),
  label: z.string().min(1),
  contribution: z.number(),
  members: z.array(contributionMemberSchema),
});

export const contributionReportSchema = z.object({
  forecast_id: z.string().min(1),
  /** Log-odds the groups are perturbations of. */
  baseline_log_odds: z.number(),
  method: z.string().min(1),
  /** Attribution is not causal identification and the UI says so. */
  method_caveat: z.string().min(1),
  groups: z.array(contributionGroupSchema),
});

/* -------------------------------------------------------------- evidence */

export const evidenceAccessSchema = z.enum(["open", "restricted", "syndicated"]);

export const evidenceItemSchema = z
  .object({
    evidence_id: z.string().min(1),
    observation_id: z.string().min(1),
    source_id: z.string().min(1),
    source_name: z.string().min(1),
    title: z.string(),
    /** Null when access is restricted: the console shows the denial, not a blank. */
    body: z.string().nullable(),
    claim: z.string(),
    stance: stanceSchema,
    modality: modalitySchema,
    reliability: probabilitySchema,
    independence_cluster: z.string().nullable(),
    cluster_size: z.number().int().positive(),
    /** True when this item restates another; the original is `syndication_of`. */
    syndication_of: z.string().nullable(),
    published_at: utcDatetimeSchema.nullable(),
    first_observed_at: utcDatetimeSchema,
    retrieved_at: utcDatetimeSchema,
    url: z.string().url().nullable(),
    span_start: z.number().int().nonnegative().nullable(),
    span_end: z.number().int().nonnegative().nullable(),
    district_ids: z.array(z.string()),
    event_family: eventFamilySchema.nullable(),
    access: evidenceAccessSchema,
    license: z.string().min(1),
    /** True when first_observed_at is after the active cutoff. */
    post_cutoff: z.boolean(),
    is_demo: z.boolean(),
  })
  .refine(
    (e) => e.span_start === null || e.span_end === null || e.span_start <= e.span_end,
    "evidence span end precedes span start",
  )
  .refine((e) => e.access !== "restricted" || e.body === null, "restricted evidence must not ship a body");

export const evidencePageSchema = z.object({
  items: z.array(evidenceItemSchema),
  total: z.number().int().nonnegative(),
  /** Items withheld by permission, counted so the analyst knows they exist. */
  withheld: z.number().int().nonnegative(),
});

/* ---------------------------------------------------------------- review */

export const reviewTaskStateSchema = z.enum([
  "pending",
  "in_review",
  "submitted",
  "adjudicated",
  "disputed",
]);

export const reviewDecisionSchema = z.enum(["accept", "correct", "reject"]);

/**
 * What a reviewer is allowed to see before submitting.
 *
 * The model's probability, status and identity are all absent by construction:
 * they are not filtered out in the UI, they are never sent. Blinding that is
 * enforced in the client is not blinding.
 */
export const blindedTaskSchema = z.object({
  task_id: z.string().min(1),
  event_family: eventFamilySchema,
  district_name: z.string().min(1),
  state: z.string().min(1),
  horizon_days: z.number().int().positive(),
  cutoff_at: utcDatetimeSchema,
  claim: z.string().min(1),
  evidence: z.array(evidenceItemSchema),
  /**
   * A machine suggestion, shown only when the task is configured to reveal it,
   * and always labelled. Null means "not revealed", not "no suggestion".
   */
  suggestion_label: z.string().nullable(),
  state_: reviewTaskStateSchema,
  /** Set once this reviewer has submitted; unblinds the peer view. */
  own_review_submitted: z.boolean(),
});

export const reviewTaskSummarySchema = z.object({
  task_id: z.string().min(1),
  event_family: eventFamilySchema,
  district_name: z.string().min(1),
  state: z.string().min(1),
  task_state: reviewTaskStateSchema,
  assigned_at: utcDatetimeSchema,
  due_at: utcDatetimeSchema,
  reviews_submitted: z.number().int().min(0).max(2),
  own_review_submitted: z.boolean(),
});

/* ------------------------------------------------------------- backtests */

export const metricSchema = z.object({
  key: z.string().min(1),
  label: z.string().min(1),
  value: z.number().nullable(),
  /** Null when the run did not compute an interval for this metric. */
  ci: z.tuple([z.number(), z.number()]).nullable(),
  /** Lower-is-better metrics render their deltas inverted. */
  lower_is_better: z.boolean(),
  unit: z.enum(["probability", "count", "ratio", "logloss"]),
  description: z.string(),
});

export const reliabilityBinSchema = z.object({
  bin_lower: probabilitySchema,
  bin_upper: probabilitySchema,
  mean_predicted: probabilitySchema,
  observed_frequency: probabilitySchema,
  count: z.number().int().nonnegative(),
});

export const curvePointSchema = z.object({ x: z.number(), y: z.number(), label: z.string().nullable() });

export const backtestArmSchema = z.object({
  arm_id: z.string().min(1),
  label: z.string().min(1),
  description: z.string(),
  metrics: z.array(metricSchema),
});

export const backtestRunSummarySchema = z.object({
  run_id: z.string().min(1),
  label: z.string().min(1),
  experiment: z.string().min(1),
  created_at: utcDatetimeSchema,
  snapshot_hash: snapshotHashSchema,
  fold_count: z.number().int().positive(),
  first_cutoff: utcDatetimeSchema,
  last_cutoff: utcDatetimeSchema,
  event_families: z.array(eventFamilySchema),
  /** Right-censored folds are excluded from scoring, and the count is shown. */
  excluded_folds: z.number().int().nonnegative(),
  is_demo: z.boolean(),
});

export const backtestRunSchema = backtestRunSummarySchema.extend({
  metrics: z.array(metricSchema),
  reliability: z.array(reliabilityBinSchema),
  pr_curve: z.array(curvePointSchema),
  budget_recall: z.array(curvePointSchema),
  abstention_risk: z.array(curvePointSchema),
  arms: z.array(backtestArmSchema),
  sample_size: z.number().int().nonnegative(),
  positive_rate: probabilitySchema,
});

/* ----------------------------------------------------------- data health */

export const sourceStatusSchema = z.enum(["healthy", "degraded", "outage"]);

export const outageSchema = z.object({
  from: utcDatetimeSchema,
  to: utcDatetimeSchema.nullable(),
  reason: z.string().min(1),
});

export const sourceHealthSchema = z.object({
  source_id: z.string().min(1),
  name: z.string().min(1),
  status: sourceStatusSchema,
  coverage: probabilitySchema,
  districts_covered: z.number().int().nonnegative(),
  median_delay_hours: z.number().nonnegative().nullable(),
  p90_delay_hours: z.number().nonnegative().nullable(),
  last_document_at: utcDatetimeSchema.nullable(),
  outages: z.array(outageSchema),
});

export const districtCoverageSchema = z.object({
  district_id: z.string().min(1),
  district_name: z.string().min(1),
  state: z.string().min(1),
  documents_30d: z.number().int().nonnegative(),
  coverage: probabilitySchema,
  /** True when coverage is thin enough that absence of signal means nothing. */
  under_covered: z.boolean(),
});

export const dataHealthSchema = z.object({
  generated_at: utcDatetimeSchema,
  snapshot_hash: snapshotHashSchema,
  sources: z.array(sourceHealthSchema),
  districts: z.array(districtCoverageSchema),
});

/* ---------------------------------------------------------------- models */

export const modelArtifactSchema = z.object({
  artifact_id: z.string().min(1),
  name: z.string().min(1),
  kind: z.enum(["generator", "calibrator", "risk_controller", "extractor", "matcher"]),
  version: z.string().min(1),
  trained_at: utcDatetimeSchema.nullable(),
  training_snapshot_hash: snapshotHashSchema.nullable(),
  code_version: z.string().min(1),
  config_hash: z.string().min(1),
  parent_artifact_ids: z.array(z.string()),
  metrics: z.array(metricSchema),
  /** Free text: what this artefact is not fit for. Always rendered. */
  limitations: z.string().min(1),
});

export const lineageNodeSchema = z.object({
  id: z.string().min(1),
  label: z.string().min(1),
  kind: z.enum(["snapshot", "run", "artifact", "dataset"]),
  at: utcDatetimeSchema.nullable(),
});

export const runLineageSchema = z.object({
  run_id: z.string().min(1),
  nodes: z.array(lineageNodeSchema),
  edges: z.array(z.object({ from: z.string().min(1), to: z.string().min(1), label: z.string() })),
});

/* -------------------------------------------------------------- scenario */

export const scenarioOverrideSchema = z.object({
  feature: z.string().min(1),
  label: z.string().min(1),
  baseline_value: z.number(),
  hypothetical_value: z.number(),
});

export const scenarioRequestSchema = z.object({
  forecast_id: z.string().min(1),
  overrides: z.array(scenarioOverrideSchema).min(1),
});

export const scenarioResultSchema = z.object({
  forecast_id: z.string().min(1),
  baseline_probability: probabilitySchema,
  hypothetical_probability: probabilitySchema,
  baseline_interval: intervalSchema.nullable(),
  hypothetical_interval: intervalSchema.nullable(),
  baseline_status: forecastStatusSchema,
  /** Deliberately not called `status`: a hypothetical never yields an alert. */
  hypothetical_status_if_real: forecastStatusSchema,
  overrides: z.array(scenarioOverrideSchema),
  /** Always true. Written by the adapter, checked by the UI, stamped on export. */
  is_hypothetical: z.literal(true),
  caveat: z.string().min(1),
});

/* ----------------------------------------------------------------- query */

export const forecastQuerySchema = z.object({
  event_family: eventFamilySchema.optional(),
  states: z.array(z.string()).optional(),
  statuses: z.array(forecastStatusSchema).optional(),
  min_probability: probabilitySchema.optional(),
  horizon_days: z.number().int().positive().optional(),
  search: z.string().optional(),
});

export const evidenceQuerySchema = z.object({
  search: z.string().optional(),
  district_id: z.string().optional(),
  event_family: eventFamilySchema.optional(),
  stance: stanceSchema.optional(),
  include_post_cutoff: z.boolean().optional(),
  limit: z.number().int().positive().max(200).optional(),
});

/* ------------------------------------------------------------------ types */

export type Probability = number;
export type EventFamily = z.infer<typeof eventFamilySchema>;
export type ForecastStatus = z.infer<typeof forecastStatusSchema>;
export type Stance = z.infer<typeof stanceSchema>;
export type Interval = z.infer<typeof intervalSchema>;
export type SnapshotInfo = z.infer<typeof snapshotInfoSchema>;
export type District = z.infer<typeof districtSchema>;
export type ForecastSummary = z.infer<typeof forecastSummarySchema>;
export type ForecastDetail = z.infer<typeof forecastDetailSchema>;
export type EvidenceRef = z.infer<typeof evidenceRefSchema>;
export type Hypothesis = z.infer<typeof hypothesisSchema>;
export type Provenance = z.infer<typeof provenanceSchema>;
export type ObservedOutcome = z.infer<typeof observedOutcomeSchema>;
export type HistoryPoint = z.infer<typeof historyPointSchema>;
export type ContributionMember = z.infer<typeof contributionMemberSchema>;
export type ContributionGroup = z.infer<typeof contributionGroupSchema>;
export type ContributionReport = z.infer<typeof contributionReportSchema>;
export type EvidenceItem = z.infer<typeof evidenceItemSchema>;
export type EvidencePage = z.infer<typeof evidencePageSchema>;
export type EvidenceAccess = z.infer<typeof evidenceAccessSchema>;
export type ReviewTaskState = z.infer<typeof reviewTaskStateSchema>;
export type ReviewDecision = z.infer<typeof reviewDecisionSchema>;
export type BlindedTask = z.infer<typeof blindedTaskSchema>;
export type ReviewTaskSummary = z.infer<typeof reviewTaskSummarySchema>;
export type Metric = z.infer<typeof metricSchema>;
export type ReliabilityBin = z.infer<typeof reliabilityBinSchema>;
export type CurvePoint = z.infer<typeof curvePointSchema>;
export type BacktestArm = z.infer<typeof backtestArmSchema>;
export type BacktestRunSummary = z.infer<typeof backtestRunSummarySchema>;
export type BacktestRun = z.infer<typeof backtestRunSchema>;
export type SourceHealth = z.infer<typeof sourceHealthSchema>;
export type DistrictCoverage = z.infer<typeof districtCoverageSchema>;
export type DataHealth = z.infer<typeof dataHealthSchema>;
export type ModelArtifact = z.infer<typeof modelArtifactSchema>;
export type RunLineage = z.infer<typeof runLineageSchema>;
export type ScenarioOverride = z.infer<typeof scenarioOverrideSchema>;
export type ScenarioRequest = z.infer<typeof scenarioRequestSchema>;
export type ScenarioResult = z.infer<typeof scenarioResultSchema>;
export type ForecastQuery = z.infer<typeof forecastQuerySchema>;
export type EvidenceQuery = z.infer<typeof evidenceQuerySchema>;
export type DataMode = z.infer<typeof dataModeSchema>;
