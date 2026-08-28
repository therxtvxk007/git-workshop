import { afterEach, describe, expect, it, vi } from "vitest";
import { RestPramaanXAdapter } from "@/lib/api/rest-adapter";
import { MockPramaanXAdapter } from "@/lib/api/mock-adapter";
import {
  AccessDeniedError,
  ApiUnavailableError,
  MalformedResponseError,
} from "@/lib/api/errors";
import {
  backtestRunSchema,
  contributionReportSchema,
  dataHealthSchema,
  districtSchema,
  evidenceItemSchema,
  forecastDetailSchema,
  historyPointSchema,
  modelArtifactSchema,
  snapshotInfoSchema,
} from "@/lib/api/types";
import { WORLD } from "@/lib/mock/dataset";

function respondWith(body: unknown, status = 200) {
  // Typed parameters, so the assertions below can read the recorded call
  // rather than casting an untyped tuple.
  return vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
    new Response(typeof body === "string" ? body : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("REST adapter", () => {
  it("14. reports a network failure as unavailable, not as bad data", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }));
    const adapter = new RestPramaanXAdapter("https://engine.invalid");
    await expect(adapter.getSnapshot()).rejects.toBeInstanceOf(ApiUnavailableError);
  });

  it("15. reports 403 as access denied", async () => {
    vi.stubGlobal("fetch", respondWith({}, 403));
    const adapter = new RestPramaanXAdapter("https://engine.invalid");
    await expect(adapter.getEvidenceItem("ev_1")).rejects.toBeInstanceOf(AccessDeniedError);
  });

  it("16. reports 501 as an unimplemented endpoint", async () => {
    vi.stubGlobal("fetch", respondWith({}, 501));
    const adapter = new RestPramaanXAdapter("https://engine.invalid");
    await expect(adapter.getDataHealth()).rejects.toBeInstanceOf(ApiUnavailableError);
  });

  it("17. rejects a 200 whose body violates the contract, listing the issues", async () => {
    vi.stubGlobal("fetch", respondWith({ snapshot_hash: "", cutoff_at: "not a date" }));
    const adapter = new RestPramaanXAdapter("https://engine.invalid");
    const error = await adapter.getSnapshot().catch((caught) => caught);
    expect(error).toBeInstanceOf(MalformedResponseError);
    expect((error as MalformedResponseError).issues.length).toBeGreaterThan(0);
  });

  it("18. never falls back to demo data when the engine fails", async () => {
    // The failure mode this asserts against: a dead engine quietly serving
    // fixtures behind a LIVE indicator.
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new Error("connection reset");
    }));
    const adapter = new RestPramaanXAdapter("https://engine.invalid");
    const result = await adapter.listForecasts({}).then(
      (rows) => ({ kind: "resolved" as const, rows }),
      (error) => ({ kind: "rejected" as const, error }),
    );
    expect(result.kind).toBe("rejected");
  });

  it("19. sends the session bearer token and never an API key", async () => {
    const fetchMock = respondWith([]);
    vi.stubGlobal("fetch", fetchMock);
    const adapter = new RestPramaanXAdapter("https://engine.invalid", async () => "session-token");
    await adapter.listDistricts();
    const headers = fetchMock.mock.calls[0]![1]!.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer session-token");
    expect(JSON.stringify(headers).toLowerCase()).not.toContain("api-key");
  });

  it("20. strips a trailing slash from the base URL", async () => {
    const fetchMock = respondWith([]);
    vi.stubGlobal("fetch", fetchMock);
    await new RestPramaanXAdapter("https://engine.invalid///").listDistricts();
    expect(fetchMock.mock.calls[0]![0]).toBe("https://engine.invalid/v1/districts");
  });
});

describe("mock adapter", () => {
  const adapter = new MockPramaanXAdapter();

  it("21. emits a dataset that satisfies every schema the REST adapter validates against", async () => {
    // This is what stops the fixtures drifting away from the contract, which
    // is how a demo passes while the real integration fails.
    expect(snapshotInfoSchema.safeParse(await adapter.getSnapshot()).success).toBe(true);
    for (const district of await adapter.listDistricts()) {
      expect(districtSchema.safeParse(district).success).toBe(true);
    }
    for (const entry of WORLD) {
      const detail = await adapter.getForecast(entry.detail.forecast_id);
      expect(forecastDetailSchema.safeParse(detail).success).toBe(true);
      expect(
        contributionReportSchema.safeParse(await adapter.getContributions(detail.forecast_id)).success,
      ).toBe(true);
      for (const point of await adapter.getForecastHistory(detail.district_id, detail.event_family)) {
        expect(historyPointSchema.safeParse(point).success).toBe(true);
      }
    }
    for (const run of await adapter.listBacktestRuns()) {
      expect(backtestRunSchema.safeParse(await adapter.getBacktestRun(run.run_id)).success).toBe(true);
    }
    expect(dataHealthSchema.safeParse(await adapter.getDataHealth()).success).toBe(true);
    for (const artifact of await adapter.listModelArtifacts()) {
      expect(modelArtifactSchema.safeParse(artifact).success).toBe(true);
    }
  });

  it("22. marks every record as demo data", async () => {
    const forecasts = await adapter.listForecasts({});
    expect(forecasts.length).toBeGreaterThan(0);
    expect(forecasts.every((f) => f.is_demo)).toBe(true);
    const evidence = await adapter.listEvidence({ limit: 200 });
    expect(evidence.items.every((e) => e.is_demo)).toBe(true);
  });

  it("23. reaches every forecast status, so no state view is unreachable", async () => {
    const statuses = new Set((await adapter.listForecasts({})).map((f) => f.status));
    expect([...statuses].sort()).toEqual(
      ["abstain", "alert", "insufficient_evidence", "monitor", "watch"],
    );
  });

  it("24. counts withheld evidence rather than silently shortening the list", async () => {
    const page = await adapter.listEvidence({ limit: 200 });
    expect(page.withheld).toBeGreaterThan(0);
    // `total` counts every match including the withheld ones, while `items` is
    // additionally capped by `limit`. Conflating the two is how a UI ends up
    // reporting a page size as if it were a result count.
    expect(page.total - page.withheld).toBeGreaterThanOrEqual(page.items.length);
    expect(page.items.every((item) => item.access !== "restricted")).toBe(true);

    // On a query small enough to fit under the limit the identity is exact.
    const restricted = WORLD.flatMap((w) => w.evidence).find((e) => e.access === "restricted")!;
    const scoped = await adapter.listEvidence({ district_id: restricted.district_ids[0], limit: 200 });
    expect(scoped.total).toBe(scoped.items.length + scoped.withheld);
    expect(scoped.withheld).toBeGreaterThan(0);
  });

  it("25. denies access to a restricted item by name instead of returning nothing", async () => {
    const restricted = WORLD.flatMap((w) => w.evidence).find((e) => e.access === "restricted");
    expect(restricted).toBeDefined();
    const error = await adapter.getEvidenceItem(restricted!.evidence_id).catch((caught) => caught);
    expect(error).toBeInstanceOf(AccessDeniedError);
    expect((error as AccessDeniedError).resource).toContain(restricted!.evidence_id);
  });

  it("26. excludes post-cutoff evidence unless it is explicitly requested", async () => {
    const withoutFuture = await adapter.listEvidence({ limit: 200 });
    expect(withoutFuture.items.some((e) => e.post_cutoff)).toBe(false);
    const withFuture = await adapter.listEvidence({ limit: 200, include_post_cutoff: true });
    expect(withFuture.items.some((e) => e.post_cutoff)).toBe(true);
  });

  it("27. validates its own evidence payloads", async () => {
    const page = await adapter.listEvidence({ limit: 50, include_post_cutoff: true });
    for (const item of page.items) {
      expect(evidenceItemSchema.safeParse(item).success).toBe(true);
    }
  });
});
