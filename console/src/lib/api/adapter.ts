import type {
  BacktestRun,
  BacktestRunSummary,
  BlindedTask,
  ContributionReport,
  DataHealth,
  District,
  EvidenceItem,
  EvidencePage,
  EvidenceQuery,
  ForecastDetail,
  ForecastQuery,
  ForecastSummary,
  HistoryPoint,
  ModelArtifact,
  ReviewTaskSummary,
  RunLineage,
  ScenarioRequest,
  ScenarioResult,
  SnapshotInfo,
} from "./types";

/**
 * Everything the console is allowed to ask the engine for.
 *
 * The interface is small and read-mostly on purpose. Forecasts, evidence and
 * metrics are *produced* by the Python engine and only *displayed* here; there
 * is no method that computes a probability, re-scores an outcome or decides a
 * status, because the console must not become a second, divergent
 * implementation of the pipeline.
 *
 * The one write is `evaluateScenario`, and even that returns a result the
 * engine marked `is_hypothetical`.
 *
 * Every method may reject with `ApiUnavailableError`, `MalformedResponseError`
 * or `AccessDeniedError` and nothing else.
 */
export interface PramaanXApiAdapter {
  /** Which snapshot, which cutoff, live or synthetic. Drives the whole shell. */
  getSnapshot(): Promise<SnapshotInfo>;

  /** The district universe, for filters, the map and the coverage join. */
  listDistricts(): Promise<District[]>;

  /** Ranked district-level forecasts for the active cutoff. */
  listForecasts(query: ForecastQuery): Promise<ForecastSummary[]>;

  /** One forecast with its hypothesis, evidence refs and provenance. */
  getForecast(forecastId: string): Promise<ForecastDetail>;

  /** The same district/family across earlier cutoffs, for the trend chart. */
  getForecastHistory(districtId: string, eventFamily: string): Promise<HistoryPoint[]>;

  /** Grouped feature attribution for one forecast. */
  getContributions(forecastId: string): Promise<ContributionReport>;

  /** Evidence search. Withheld items are counted, never silently dropped. */
  listEvidence(query: EvidenceQuery): Promise<EvidencePage>;

  /** One evidence item, including the span the claim was extracted from. */
  getEvidenceItem(evidenceId: string): Promise<EvidenceItem>;

  /** The signed-in reviewer's queue. */
  listReviewTasks(): Promise<ReviewTaskSummary[]>;

  /** A review task with the model's own opinion withheld by construction. */
  getReviewTask(taskId: string): Promise<BlindedTask>;

  /** Evaluation runs available for inspection and comparison. */
  listBacktestRuns(): Promise<BacktestRunSummary[]>;

  /** One run: metrics, reliability, PR, budget-recall, abstention-risk, arms. */
  getBacktestRun(runId: string): Promise<BacktestRun>;

  /** Source coverage, ingestion delay and outages. */
  getDataHealth(): Promise<DataHealth>;

  /** Model artefacts with their training snapshot and stated limitations. */
  listModelArtifacts(): Promise<ModelArtifact[]>;

  /** Snapshot -> run -> artefact lineage for one run. */
  getRunLineage(runId: string): Promise<RunLineage>;

  /** Baseline versus hypothetical. Never writes to the forecast namespace. */
  evaluateScenario(request: ScenarioRequest): Promise<ScenarioResult>;
}

/** How the active adapter was selected, surfaced in the top bar. */
export interface AdapterMode {
  mode: "mock" | "rest";
  /** Present in REST mode. Never contains a key. */
  baseUrl?: string;
  label: string;
  description: string;
}
