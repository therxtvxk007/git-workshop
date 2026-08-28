import { describe, expect, it } from "vitest";
import {
  distributionSchema,
  evidenceItemSchema,
  forecastSummarySchema,
  intervalSchema,
  scenarioResultSchema,
  utcDatetimeSchema,
} from "@/lib/api/types";

/**
 * Contract tests.
 *
 * Each case is a payload the engine could plausibly emit after a regression,
 * and each one must be refused rather than rendered. A console that displays a
 * probability of 1.4 as "140% likely" has failed at the only job that matters.
 */

const VALID = {
  forecast_id: "fc_1",
  district_id: "LGD-001",
  district_name: "Patna",
  state: "Bihar",
  event_family: "flood" as const,
  cutoff_at: "2026-01-15T00:00:00Z",
  created_at: "2026-01-15T02:00:00Z",
  horizon_days: 30,
  raw_probability: 0.42,
  calibrated_probability: 0.42,
  interval: { lower: 0.3, upper: 0.55, coverage: 0.9, method: "split_conformal@v0" },
  epistemic_uncertainty: 0.2,
  base_rate: 0.07,
  status: "watch" as const,
  evidence_count: 5,
  independent_cluster_count: 3,
  snapshot_hash: "sha256:abc",
  is_demo: true,
};

describe("forecast contract", () => {
  it("1. accepts a well-formed forecast", () => {
    expect(forecastSummarySchema.safeParse(VALID).success).toBe(true);
  });

  it("2. rejects a probability above 1", () => {
    const result = forecastSummarySchema.safeParse({ ...VALID, calibrated_probability: 1.4 });
    expect(result.success).toBe(false);
    expect(JSON.stringify(result)).toContain("probability above 1");
  });

  it("3. rejects a negative probability", () => {
    expect(forecastSummarySchema.safeParse({ ...VALID, raw_probability: -0.01 }).success).toBe(false);
  });

  it("4. rejects a one-sided interval", () => {
    // A missing bound silently filled in with the point estimate looks tight
    // and confident, which is the opposite of what a missing bound means.
    const oneSided = { lower: 0.3, coverage: 0.9, method: "split_conformal@v0" };
    expect(intervalSchema.safeParse(oneSided).success).toBe(false);
  });

  it("5. rejects an inverted interval", () => {
    const inverted = { lower: 0.8, upper: 0.2, coverage: 0.9, method: "m" };
    const result = intervalSchema.safeParse(inverted);
    expect(result.success).toBe(false);
    expect(JSON.stringify(result)).toContain("lower bound exceeds upper bound");
  });

  it("6. rejects a blank snapshot hash", () => {
    const result = forecastSummarySchema.safeParse({ ...VALID, snapshot_hash: "   " });
    expect(result.success).toBe(false);
    expect(JSON.stringify(result)).toContain("snapshot_hash");
  });

  it("7. rejects an unknown status", () => {
    expect(forecastSummarySchema.safeParse({ ...VALID, status: "critical" }).success).toBe(false);
  });

  it("8. rejects created_at preceding cutoff_at", () => {
    const result = forecastSummarySchema.safeParse({
      ...VALID,
      created_at: "2026-01-14T23:00:00Z",
    });
    expect(result.success).toBe(false);
    expect(JSON.stringify(result)).toContain("created_at precedes cutoff_at");
  });

  it("9. rejects more independent clusters than evidence items", () => {
    const result = forecastSummarySchema.safeParse({
      ...VALID,
      evidence_count: 2,
      independent_cluster_count: 5,
    });
    expect(result.success).toBe(false);
    expect(JSON.stringify(result)).toContain("independent clusters cannot outnumber");
  });

  it("10. rejects a timestamp with no timezone", () => {
    // A guessed timezone is a cutoff bug waiting to happen.
    expect(utcDatetimeSchema.safeParse("2026-01-15T00:00:00").success).toBe(false);
    expect(utcDatetimeSchema.safeParse("2026-01-15T00:00:00Z").success).toBe(true);
    expect(utcDatetimeSchema.safeParse("2026-01-15T05:30:00+05:30").success).toBe(true);
  });

  it("11. rejects a categorical distribution that does not sum to 1", () => {
    expect(distributionSchema.safeParse({ low: 0.3, high: 0.3 }).success).toBe(false);
    expect(distributionSchema.safeParse({ low: 0.4, high: 0.6 }).success).toBe(true);
    // An empty map means "no opinion" and is allowed.
    expect(distributionSchema.safeParse({}).success).toBe(true);
  });

  it("12. refuses restricted evidence that still carries a body", () => {
    const base = {
      evidence_id: "ev_1",
      observation_id: "obs_1",
      source_id: "acled",
      source_name: "ACLED",
      title: "t",
      body: "the full text",
      claim: "c",
      stance: "supports" as const,
      modality: "asserted" as const,
      reliability: 0.5,
      independence_cluster: null,
      cluster_size: 1,
      syndication_of: null,
      published_at: null,
      first_observed_at: "2026-01-10T00:00:00Z",
      retrieved_at: "2026-01-10T01:00:00Z",
      url: null,
      span_start: 0,
      span_end: 1,
      district_ids: [],
      event_family: null,
      access: "restricted" as const,
      license: "ACLED licence",
      post_cutoff: false,
      is_demo: true,
    };
    expect(evidenceItemSchema.safeParse(base).success).toBe(false);
    expect(evidenceItemSchema.safeParse({ ...base, body: null }).success).toBe(true);
  });

  it("13. will not accept a scenario result that claims not to be hypothetical", () => {
    const result = scenarioResultSchema.safeParse({
      forecast_id: "fc_1",
      baseline_probability: 0.4,
      hypothetical_probability: 0.6,
      baseline_interval: null,
      hypothetical_interval: null,
      baseline_status: "watch",
      hypothetical_status_if_real: "alert",
      overrides: [],
      is_hypothetical: false,
      caveat: "x",
    });
    expect(result.success).toBe(false);
  });
});
