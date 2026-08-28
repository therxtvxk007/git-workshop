import type { PramaanXApiAdapter } from "./adapter";
import { AccessDeniedError, ApiUnavailableError, MalformedResponseError } from "./errors";
import {
  backtestRunSchema,
  backtestRunSummarySchema,
  blindedTaskSchema,
  contributionReportSchema,
  dataHealthSchema,
  districtSchema,
  evidenceItemSchema,
  evidencePageSchema,
  forecastDetailSchema,
  forecastSummarySchema,
  historyPointSchema,
  modelArtifactSchema,
  reviewTaskSummarySchema,
  runLineageSchema,
  scenarioResultSchema,
  snapshotInfoSchema,
  type EvidenceQuery,
  type ForecastQuery,
  type ForecastSummary,
  type ScenarioRequest,
} from "./types";
import {
  MOCK_ARTIFACTS,
  MOCK_DATA_HEALTH,
  MOCK_LINEAGE,
  MOCK_REVIEW_TASKS,
  MOCK_RUNS,
  MOCK_SNAPSHOT,
  WORLD,
} from "@/lib/mock/dataset";
import { MOCK_DISTRICTS } from "@/lib/mock/districts";
import { z } from "zod";

/**
 * The offline adapter.
 *
 * It validates its own output against exactly the schemas the REST adapter
 * validates responses with. That is not belt-and-braces: it is the only thing
 * that keeps the fixtures and the contract from drifting apart, and a fixture
 * that has drifted is a demo that passes while the real integration fails.
 */
export class MockPramaanXAdapter implements PramaanXApiAdapter {
  private check<T extends z.ZodTypeAny>(endpoint: string, schema: T, value: unknown): z.infer<T> {
    const parsed = schema.safeParse(value);
    if (!parsed.success) {
      throw new MalformedResponseError(
        endpoint,
        parsed.error.issues.map((i) => `${i.path.join(".") || "<root>"}: ${i.message}`),
      );
    }
    return parsed.data;
  }

  private find(forecastId: string) {
    const entry = WORLD.find((w) => w.detail.forecast_id === forecastId);
    if (!entry) throw new ApiUnavailableError(`/v1/forecasts/${forecastId}`, "No such forecast in the demo dataset");
    return entry;
  }

  async getSnapshot() {
    return this.check("/v1/snapshot", snapshotInfoSchema, MOCK_SNAPSHOT);
  }

  async listDistricts() {
    return this.check("/v1/districts", z.array(districtSchema), MOCK_DISTRICTS);
  }

  async listForecasts(query: ForecastQuery) {
    const needle = query.search?.trim().toLowerCase();
    const rows = WORLD.map((w) => {
      const { hypothesis: _h, evidence: _e, provenance: _p, observed_outcome: _o, ...summary } = w.detail;
      return summary as ForecastSummary;
    }).filter((f) => {
      if (query.event_family && f.event_family !== query.event_family) return false;
      if (query.states?.length && !query.states.includes(f.state)) return false;
      if (query.statuses?.length && !query.statuses.includes(f.status)) return false;
      if (query.min_probability !== undefined && f.calibrated_probability < query.min_probability) return false;
      if (query.horizon_days !== undefined && f.horizon_days !== query.horizon_days) return false;
      if (needle) {
        const haystack = `${f.district_name} ${f.state} ${f.event_family}`.toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      return true;
    });
    return this.check("/v1/forecasts", z.array(forecastSummarySchema), rows);
  }

  async getForecast(forecastId: string) {
    return this.check(`/v1/forecasts/${forecastId}`, forecastDetailSchema, this.find(forecastId).detail);
  }

  async getForecastHistory(districtId: string, eventFamily: string) {
    const entry = WORLD.find(
      (w) => w.detail.district_id === districtId && w.detail.event_family === eventFamily,
    );
    if (!entry) {
      // No history is a legitimate answer for a district/family pair that has
      // never been scored, and it is not the same thing as an error.
      return [];
    }
    return this.check("/v1/forecasts/history", z.array(historyPointSchema), entry.history);
  }

  async getContributions(forecastId: string) {
    return this.check(
      `/v1/forecasts/${forecastId}/contributions`,
      contributionReportSchema,
      this.find(forecastId).contributions,
    );
  }

  async listEvidence(query: EvidenceQuery) {
    const needle = query.search?.trim().toLowerCase();
    const all = WORLD.flatMap((w) => w.evidence);
    const matched = all.filter((e) => {
      if (query.district_id && !e.district_ids.includes(query.district_id)) return false;
      if (query.event_family && e.event_family !== query.event_family) return false;
      if (query.stance && e.stance !== query.stance) return false;
      if (!query.include_post_cutoff && e.post_cutoff) return false;
      if (needle) {
        const haystack = `${e.title} ${e.claim} ${e.source_name}`.toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      return true;
    });

    // Restricted items are counted but not returned. A silently shortened list
    // reads as "there is nothing more", which is the wrong belief to install.
    const visible = matched.filter((e) => e.access !== "restricted");
    const limit = query.limit ?? 50;
    return this.check("/v1/evidence", evidencePageSchema, {
      items: visible.slice(0, limit),
      total: matched.length,
      withheld: matched.length - visible.length,
    });
  }

  async getEvidenceItem(evidenceId: string) {
    const item = WORLD.flatMap((w) => w.evidence).find((e) => e.evidence_id === evidenceId);
    if (!item) throw new ApiUnavailableError(`/v1/evidence/${evidenceId}`, "No such evidence item");
    if (item.access === "restricted") {
      throw new AccessDeniedError(`evidence ${evidenceId} (${item.source_name})`, "analyst");
    }
    return this.check(`/v1/evidence/${evidenceId}`, evidenceItemSchema, item);
  }

  async listReviewTasks() {
    return this.check("/v1/review/tasks", z.array(reviewTaskSummarySchema), MOCK_REVIEW_TASKS);
  }

  async getReviewTask(taskId: string) {
    const summary = MOCK_REVIEW_TASKS.find((t) => t.task_id === taskId);
    if (!summary) throw new ApiUnavailableError(`/v1/review/tasks/${taskId}`, "No such review task");
    const entry = WORLD.find((w) => w.detail.forecast_id === `fc_${taskId.slice(5)}`);
    if (!entry) throw new ApiUnavailableError(`/v1/review/tasks/${taskId}`, "Task is not linked to a forecast");

    // Note what is *absent*: no probability, no status, no model identity. The
    // blinding is in the payload, not in the component that renders it.
    const blinded = {
      task_id: summary.task_id,
      event_family: summary.event_family,
      district_name: summary.district_name,
      state: summary.state,
      horizon_days: entry.detail.horizon_days,
      cutoff_at: entry.detail.cutoff_at,
      claim:
        `Will a ${summary.event_family.replace(/_/g, " ")} event occur in ` +
        `${summary.district_name}, ${summary.state} within ${entry.detail.horizon_days} days of the cutoff?`,
      evidence: entry.evidence.filter((e) => !e.post_cutoff && e.access !== "restricted"),
      suggestion_label: summary.own_review_submitted ? "Model suggested: WATCH" : null,
      state_: summary.task_state,
      own_review_submitted: summary.own_review_submitted,
    };
    return this.check(`/v1/review/tasks/${taskId}`, blindedTaskSchema, blinded);
  }

  async listBacktestRuns() {
    const summaries = MOCK_RUNS.map(({ metrics: _m, reliability: _r, pr_curve: _p, budget_recall: _b, abstention_risk: _a, arms: _ar, sample_size: _s, positive_rate: _pr, ...rest }) => rest);
    return this.check("/v1/backtests", z.array(backtestRunSummarySchema), summaries);
  }

  async getBacktestRun(runId: string) {
    const run = MOCK_RUNS.find((r) => r.run_id === runId);
    if (!run) throw new ApiUnavailableError(`/v1/backtests/${runId}`, "No such evaluation run");
    return this.check(`/v1/backtests/${runId}`, backtestRunSchema, run);
  }

  async getDataHealth() {
    return this.check("/v1/data-health", dataHealthSchema, MOCK_DATA_HEALTH);
  }

  async listModelArtifacts() {
    return this.check("/v1/models", z.array(modelArtifactSchema), MOCK_ARTIFACTS);
  }

  async getRunLineage(runId: string) {
    const lineage = MOCK_LINEAGE[runId];
    if (!lineage) throw new ApiUnavailableError(`/v1/runs/${runId}/lineage`, "No lineage recorded for this run");
    return this.check(`/v1/runs/${runId}/lineage`, runLineageSchema, lineage);
  }

  async evaluateScenario(request: ScenarioRequest) {
    const entry = this.find(request.forecast_id);
    const base = entry.detail.calibrated_probability;

    // The scenario arithmetic is a transparent, documented toy: a logit shift
    // proportional to the override deltas. It is NOT the engine's model, and
    // the caveat that ships with every result says so. Anything cleverer here
    // would be the console quietly forecasting on its own.
    const logit = Math.log(Math.max(base, 1e-6) / Math.max(1 - base, 1e-6));
    const shift = request.overrides.reduce(
      (acc, o) => acc + (o.hypothetical_value - o.baseline_value) * 0.18,
      0,
    );
    const hypothetical = 1 / (1 + Math.exp(-(logit + shift)));

    return this.check("/v1/scenarios/evaluate", scenarioResultSchema, {
      forecast_id: request.forecast_id,
      baseline_probability: base,
      hypothetical_probability: Number(hypothetical.toFixed(4)),
      baseline_interval: entry.detail.interval,
      hypothetical_interval: entry.detail.interval
        ? {
            ...entry.detail.interval,
            lower: Math.max(0, Number((hypothetical - 0.12).toFixed(4))),
            upper: Math.min(1, Number((hypothetical + 0.14).toFixed(4))),
          }
        : null,
      baseline_status: entry.detail.status,
      hypothetical_status_if_real:
        hypothetical > 0.62 ? "alert" : hypothetical > 0.34 ? "watch" : "monitor",
      overrides: request.overrides,
      is_hypothetical: true as const,
      caveat:
        "Hypothetical. Produced by a documented toy transform in the console, not by the " +
        "Pramaan-X engine. It cannot become an alert, is never written to the forecast " +
        "namespace, and every export of it is watermarked.",
    });
  }
}
