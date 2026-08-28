import { beforeEach, describe, expect, it } from "vitest";
import { MockPramaanXAdapter } from "@/lib/api/mock-adapter";
import { LocalCloudBackend } from "@/lib/cloud/local-backend";
import { MOCK_REVIEW_TASKS } from "@/lib/mock/dataset";

/**
 * Blinding and immutability.
 *
 * The database is where these rules are actually enforced (see
 * supabase/tests/01_rls_test.sql, which attempts the same violations against
 * real Postgres). These tests cover the client-side half: that the blinded
 * payload does not carry the model's opinion in the first place, and that the
 * local backend reproduces the rules faithfully enough to demo them.
 */

describe("blinded review payload", () => {
  const adapter = new MockPramaanXAdapter();
  const taskId = MOCK_REVIEW_TASKS[0]!.task_id;

  it("41. omits the model's probability, status and identity entirely", async () => {
    const task = await adapter.getReviewTask(taskId);
    const serialised = JSON.stringify(task);
    // Not "the UI hides them" — they are absent from the response. Blinding
    // enforced in the client is not blinding.
    expect(serialised).not.toContain("calibrated_probability");
    expect(serialised).not.toContain("raw_probability");
    expect(serialised).not.toContain("model_versions");
    expect(serialised).not.toContain("generated_by");
    expect(Object.keys(task)).not.toContain("status");
  });

  it("42. shows the reviewer only evidence the model itself could use", async () => {
    const task = await adapter.getReviewTask(taskId);
    expect(task.evidence.length).toBeGreaterThan(0);
    expect(task.evidence.every((item) => !item.post_cutoff)).toBe(true);
    expect(task.evidence.every((item) => item.access !== "restricted")).toBe(true);
  });

  it("43. withholds the machine suggestion until the reviewer has submitted", async () => {
    const unsubmitted = MOCK_REVIEW_TASKS.find((t) => !t.own_review_submitted)!;
    const submitted = MOCK_REVIEW_TASKS.find((t) => t.own_review_submitted)!;
    expect((await adapter.getReviewTask(unsubmitted.task_id)).suggestion_label).toBeNull();
    expect((await adapter.getReviewTask(submitted.task_id)).suggestion_label).not.toBeNull();
  });
});

describe("local backend review rules", () => {
  let backend: LocalCloudBackend;

  beforeEach(async () => {
    localStorage.clear();
    backend = new LocalCloudBackend();
    await backend.signIn("reviewer@demo.invalid", "demo");
  });

  const submission = {
    taskId: "task_demo",
    decision: "accept" as const,
    correctedProbability: null,
    rationale: "Two independent clusters support the claim before the cutoff.",
    evidenceIds: [],
    sawSuggestion: false,
    timeSpentSeconds: 90,
  };

  it("44. refuses a second review of the same task by the same reviewer", async () => {
    await backend.submitReview(submission);
    await expect(backend.submitReview(submission)).rejects.toThrow(/immutable/i);
  });

  it("45. hides a peer review until the caller has submitted their own", async () => {
    await backend.submitReview(submission);
    await backend.signOut();
    await backend.signIn("peer@demo.invalid", "demo");
    expect(await backend.listReviews("task_demo")).toHaveLength(0);

    await backend.submitReview({
      ...submission,
      decision: "reject",
      rationale: "The supporting reports are rewrites of a single wire story.",
    });
    expect(await backend.listReviews("task_demo")).toHaveLength(2);
  });

  it("46. refuses adjudication to a non-administrator", async () => {
    await expect(
      backend.adjudicate("task_demo", "accept", null, "Trying to adjudicate without the role."),
    ).rejects.toThrow(/administrator/i);
  });

  it("47. gives a new sign-up the viewer role and nothing more", async () => {
    await backend.signOut();
    const user = await backend.signUp("fresh@demo.invalid", "pw", "Fresh Analyst");
    expect(user.roles).toEqual(["viewer"]);
  });

  it("48. chains audit entries and detects a broken chain", async () => {
    await backend.submitReview(submission);
    await backend.submitReview({ ...submission, taskId: "task_demo_2" });
    expect(await backend.verifyAuditChain()).toEqual({ ok: true, brokenAt: null });

    // Tamper the way an attacker with storage access would.
    const key = "pramaanx.console.v1.audit";
    const events = JSON.parse(localStorage.getItem(key)!);
    events[0].detail = { decision: "reject" };
    localStorage.setItem(key, JSON.stringify(events));

    const verified = await backend.verifyAuditChain();
    expect(verified.ok).toBe(false);
    expect(verified.brokenAt).toBe(events[0].id);
  });

  it("49. records every export with its cutoff, snapshot and demo status", async () => {
    await backend.recordExport({
      exportName: "ranked-districts",
      format: "csv",
      rowCount: 42,
      cutoffAt: "2026-01-15T00:00:00Z",
      snapshotHash: "sha256:demo",
      dataMode: "synthetic",
      isHypothetical: false,
    });
    const [record] = await backend.listExports();
    expect(record).toMatchObject({ rowCount: 42, dataMode: "synthetic", format: "csv" });
    const audit = await backend.listAudit();
    expect(audit.some((event) => event.action === "export.create")).toBe(true);
  });
});

describe("scenario isolation", () => {
  it("50. always marks a scenario result hypothetical, whatever was asked for", async () => {
    const adapter = new MockPramaanXAdapter();
    const forecast = (await adapter.listForecasts({}))[0]!;
    const result = await adapter.evaluateScenario({
      forecast_id: forecast.forecast_id,
      overrides: [
        { feature: "evidence.support_weight", label: "Support", baseline_value: 1, hypothetical_value: 9 },
      ],
    });
    expect(result.is_hypothetical).toBe(true);
    // The field is named so it cannot be mistaken for a live status.
    expect(result).toHaveProperty("hypothetical_status_if_real");
    expect(result).not.toHaveProperty("status");
    expect(result.caveat).toMatch(/hypothetical/i);
  });

  it("51. never writes a scenario into the forecast namespace", async () => {
    const adapter = new MockPramaanXAdapter();
    const before = await adapter.listForecasts({});
    await adapter.evaluateScenario({
      forecast_id: before[0]!.forecast_id,
      overrides: [
        { feature: "recency.claims_7d", label: "Claims", baseline_value: 0, hypothetical_value: 12 },
      ],
    });
    const after = await adapter.listForecasts({});
    expect(after).toHaveLength(before.length);
    expect(after[0]!.calibrated_probability).toBe(before[0]!.calibrated_probability);
  });
});
