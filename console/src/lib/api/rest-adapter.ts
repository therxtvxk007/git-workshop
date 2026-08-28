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
  type ScenarioRequest,
} from "./types";
import { AccessDeniedError, ApiUnavailableError, MalformedResponseError } from "./errors";
import type { PramaanXApiAdapter } from "./adapter";
import { z } from "zod";

/**
 * Talks to a live Pramaan-X serving API.
 *
 * Three rules hold throughout, and each exists because the alternative
 * produces a console that lies:
 *
 *  1. **No fallback to mock data.** If the engine is down, the analyst sees
 *     "unavailable". A console that silently substitutes demo numbers for a
 *     dead endpoint is worse than one that shows nothing.
 *  2. **Every response is validated** against the same schema the mock adapter
 *     satisfies. A 200 with a malformed body is a `MalformedResponseError`.
 *  3. **No API key ever reaches this file.** Authenticated calls go through a
 *     server-side proxy (see docs/API_INTEGRATION.md); the browser sends the
 *     user's session bearer token and nothing else.
 */
export class RestPramaanXAdapter implements PramaanXApiAdapter {
  private readonly baseUrl: string;
  private readonly getAuthToken: () => Promise<string | null>;

  constructor(baseUrl: string, getAuthToken: () => Promise<string | null> = async () => null) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.getAuthToken = getAuthToken;
  }

  private async request<T extends z.ZodTypeAny>(
    path: string,
    schema: T,
    init?: RequestInit,
  ): Promise<z.infer<T>> {
    const url = `${this.baseUrl}${path}`;
    let response: Response;
    try {
      const token = await this.getAuthToken();
      response = await fetch(url, {
        ...init,
        headers: {
          Accept: "application/json",
          ...(init?.body ? { "Content-Type": "application/json" } : {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...init?.headers,
        },
      });
    } catch (cause) {
      // A network failure is unavailability, not malformed data. Keeping them
      // apart is what lets the UI say "the engine is unreachable" rather than
      // "the engine is broken".
      throw new ApiUnavailableError(path, `Could not reach the engine at ${url}`, cause);
    }

    if (response.status === 401 || response.status === 403) {
      throw new AccessDeniedError(path);
    }
    if (response.status === 501 || response.status === 404) {
      throw new ApiUnavailableError(path, `The engine has not implemented ${path}`);
    }
    if (!response.ok) {
      throw new ApiUnavailableError(path, `Engine returned HTTP ${response.status} for ${path}`);
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch (cause) {
      throw new MalformedResponseError(path, [`response body is not JSON: ${String(cause)}`]);
    }

    const parsed = schema.safeParse(payload);
    if (!parsed.success) {
      throw new MalformedResponseError(
        path,
        parsed.error.issues.map((i) => `${i.path.join(".") || "<root>"}: ${i.message}`),
      );
    }
    return parsed.data;
  }

  private static query(params: Record<string, string | number | boolean | string[] | undefined>) {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined) continue;
      if (Array.isArray(value)) {
        for (const entry of value) search.append(key, entry);
      } else {
        search.set(key, String(value));
      }
    }
    const encoded = search.toString();
    return encoded ? `?${encoded}` : "";
  }

  getSnapshot() {
    return this.request("/v1/snapshot", snapshotInfoSchema);
  }

  listDistricts() {
    return this.request("/v1/districts", z.array(districtSchema));
  }

  listForecasts(query: ForecastQuery) {
    const qs = RestPramaanXAdapter.query({
      event_family: query.event_family,
      states: query.states,
      statuses: query.statuses,
      min_probability: query.min_probability,
      horizon_days: query.horizon_days,
      search: query.search,
    });
    return this.request(`/v1/forecasts${qs}`, z.array(forecastSummarySchema));
  }

  getForecast(forecastId: string) {
    return this.request(`/v1/forecasts/${encodeURIComponent(forecastId)}`, forecastDetailSchema);
  }

  getForecastHistory(districtId: string, eventFamily: string) {
    const qs = RestPramaanXAdapter.query({ district_id: districtId, event_family: eventFamily });
    return this.request(`/v1/forecasts/history${qs}`, z.array(historyPointSchema));
  }

  getContributions(forecastId: string) {
    return this.request(
      `/v1/forecasts/${encodeURIComponent(forecastId)}/contributions`,
      contributionReportSchema,
    );
  }

  listEvidence(query: EvidenceQuery) {
    const qs = RestPramaanXAdapter.query({
      search: query.search,
      district_id: query.district_id,
      event_family: query.event_family,
      stance: query.stance,
      include_post_cutoff: query.include_post_cutoff,
      limit: query.limit,
    });
    return this.request(`/v1/evidence${qs}`, evidencePageSchema);
  }

  getEvidenceItem(evidenceId: string) {
    return this.request(`/v1/evidence/${encodeURIComponent(evidenceId)}`, evidenceItemSchema);
  }

  listReviewTasks() {
    return this.request("/v1/review/tasks", z.array(reviewTaskSummarySchema));
  }

  getReviewTask(taskId: string) {
    return this.request(`/v1/review/tasks/${encodeURIComponent(taskId)}`, blindedTaskSchema);
  }

  listBacktestRuns() {
    return this.request("/v1/backtests", z.array(backtestRunSummarySchema));
  }

  getBacktestRun(runId: string) {
    return this.request(`/v1/backtests/${encodeURIComponent(runId)}`, backtestRunSchema);
  }

  getDataHealth() {
    return this.request("/v1/data-health", dataHealthSchema);
  }

  listModelArtifacts() {
    return this.request("/v1/models", z.array(modelArtifactSchema));
  }

  getRunLineage(runId: string) {
    return this.request(`/v1/runs/${encodeURIComponent(runId)}/lineage`, runLineageSchema);
  }

  evaluateScenario(request: ScenarioRequest) {
    return this.request("/v1/scenarios/evaluate", scenarioResultSchema, {
      method: "POST",
      body: JSON.stringify(request),
    });
  }
}
