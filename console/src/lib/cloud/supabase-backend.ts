import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type {
  Adjudication,
  AppRole,
  AuditEvent,
  CloudBackend,
  CloudUser,
  Dispute,
  ExportRecord,
  ReviewDecisionValue,
  ReviewSubmission,
  SavedView,
  ScenarioSessionRecord,
  StoredReview,
} from "./types";

/**
 * The Postgres-backed implementation of `CloudBackend`.
 *
 * Almost every method here is a plain query. That is the point: the rules live
 * in supabase/migrations as policies and constraints, so this file cannot
 * weaken them and does not try. Where a method looks suspiciously trusting —
 * `listReviews` fetching every review for a task, for instance — it is because
 * the blinding policy has already decided what the caller may see, and
 * re-filtering here would only hide which layer is responsible.
 */
export class SupabaseCloudBackend implements CloudBackend {
  readonly kind = "supabase" as const;
  private client: SupabaseClient;

  constructor(url: string, anonKey: string) {
    this.client = createClient(url, anonKey, {
      auth: { persistSession: true, autoRefreshToken: true },
    });
  }

  private async hydrate(userId: string, email: string): Promise<CloudUser> {
    const [{ data: profile }, { data: roles }] = await Promise.all([
      this.client.from("profiles").select("display_name").eq("id", userId).maybeSingle(),
      this.client.from("user_roles").select("role").eq("user_id", userId),
    ]);
    return {
      id: userId,
      email,
      displayName: (profile?.display_name as string | undefined) ?? email.split("@")[0] ?? "Analyst",
      roles: ((roles ?? []) as { role: AppRole }[]).map((r) => r.role),
    };
  }

  async getCurrentUser(): Promise<CloudUser | null> {
    const { data } = await this.client.auth.getUser();
    if (!data.user) return null;
    return this.hydrate(data.user.id, data.user.email ?? "");
  }

  onAuthChange(listener: (user: CloudUser | null) => void): () => void {
    const { data } = this.client.auth.onAuthStateChange(async (_event, session) => {
      listener(session?.user ? await this.hydrate(session.user.id, session.user.email ?? "") : null);
    });
    return () => data.subscription.unsubscribe();
  }

  async signIn(email: string, password: string): Promise<CloudUser> {
    const { data, error } = await this.client.auth.signInWithPassword({ email, password });
    if (error || !data.user) throw new Error(error?.message ?? "Sign-in failed.");
    return this.hydrate(data.user.id, data.user.email ?? email);
  }

  async signUp(email: string, password: string, displayName: string): Promise<CloudUser> {
    const { data, error } = await this.client.auth.signUp({
      email,
      password,
      options: { data: { display_name: displayName } },
    });
    if (error || !data.user) throw new Error(error?.message ?? "Sign-up failed.");
    // The profile row and the `viewer` role are created by handle_new_user(),
    // not here: a client that creates its own role row is a client that can
    // choose its own role.
    return this.hydrate(data.user.id, data.user.email ?? email);
  }

  async signOut(): Promise<void> {
    await this.client.auth.signOut();
  }

  async getAccessToken(): Promise<string | null> {
    const { data } = await this.client.auth.getSession();
    return data.session?.access_token ?? null;
  }

  /* ------------------------------------------------------------ views */

  async listSavedViews(): Promise<SavedView[]> {
    const { data, error } = await this.client
      .from("saved_views")
      .select("*")
      .order("updated_at", { ascending: false });
    if (error) throw new Error(error.message);
    return (data ?? []).map((row) => ({
      id: row.id as string,
      name: row.name as string,
      route: row.route as string,
      filters: (row.filters ?? {}) as Record<string, unknown>,
      cutoffAt: row.cutoff_at as string,
      snapshotHash: row.snapshot_hash as string,
      isShared: row.is_shared as boolean,
      ownerId: row.owner_id as string,
      updatedAt: row.updated_at as string,
    }));
  }

  async saveView(view: Omit<SavedView, "id" | "ownerId" | "updatedAt">): Promise<SavedView> {
    const user = await this.requireUser();
    const { data, error } = await this.client
      .from("saved_views")
      .insert({
        owner_id: user.id,
        name: view.name,
        route: view.route,
        filters: view.filters,
        cutoff_at: view.cutoffAt,
        snapshot_hash: view.snapshotHash,
        is_shared: view.isShared,
      })
      .select()
      .single();
    if (error) throw new Error(error.message);
    return { ...view, id: data.id as string, ownerId: user.id, updatedAt: data.updated_at as string };
  }

  async deleteView(id: string): Promise<void> {
    const { error } = await this.client.from("saved_views").delete().eq("id", id);
    if (error) throw new Error(error.message);
  }

  /* ----------------------------------------------------------- review */

  async listReviews(taskId: string): Promise<StoredReview[]> {
    // No client-side blinding filter: `reviews_select_blinded` already applied.
    const { data, error } = await this.client
      .from("annotation_reviews")
      .select("*")
      .eq("task_id", taskId)
      .order("submitted_at");
    if (error) throw new Error(error.message);
    return (data ?? []).map((row) => ({
      id: row.id as string,
      taskId: row.task_id as string,
      reviewerId: row.reviewer_id as string,
      reviewerLabel: `Reviewer ${(row.reviewer_id as string).slice(0, 6)}`,
      decision: row.decision as ReviewDecisionValue,
      correctedProbability: row.corrected_probability === null ? null : Number(row.corrected_probability),
      rationale: row.rationale as string,
      evidenceIds: (row.evidence_ids ?? []) as string[],
      sawSuggestion: row.saw_suggestion as boolean,
      timeSpentSeconds: (row.time_spent_seconds ?? 0) as number,
      submittedAt: row.submitted_at as string,
    }));
  }

  async submitReview(submission: ReviewSubmission): Promise<StoredReview> {
    const user = await this.requireUser();
    const { data, error } = await this.client
      .from("annotation_reviews")
      .insert({
        task_id: submission.taskId,
        reviewer_id: user.id,
        decision: submission.decision,
        corrected_probability: submission.correctedProbability,
        rationale: submission.rationale,
        evidence_ids: submission.evidenceIds,
        saw_suggestion: submission.sawSuggestion,
        time_spent_seconds: submission.timeSpentSeconds,
      })
      .select()
      .single();
    if (error) {
      // A unique violation here is the immutability guarantee doing its job,
      // so it gets a sentence an analyst can act on rather than a Postgres code.
      if (error.code === "23505") {
        throw new Error("You have already submitted a review for this task. Reviews are immutable.");
      }
      throw new Error(error.message);
    }
    await this.appendAudit({
      action: "review.submit",
      resourceType: "annotation_review",
      resourceId: submission.taskId,
      cutoffAt: null,
      snapshotHash: null,
      detail: { decision: submission.decision, saw_suggestion: submission.sawSuggestion },
    });
    return { ...submission, id: data.id as string, reviewerId: user.id, reviewerLabel: user.displayName, submittedAt: data.submitted_at as string };
  }

  async adjudicate(
    taskId: string,
    decision: ReviewDecisionValue,
    finalProbability: number | null,
    rationale: string,
  ): Promise<Adjudication> {
    const user = await this.requireUser();
    const { data, error } = await this.client
      .from("annotation_adjudications")
      .insert({
        task_id: taskId,
        adjudicator_id: user.id,
        decision,
        final_probability: finalProbability,
        rationale,
      })
      .select()
      .single();
    if (error) throw new Error(error.message);
    await this.appendAudit({
      action: "review.adjudicate",
      resourceType: "annotation_adjudication",
      resourceId: taskId,
      cutoffAt: null,
      snapshotHash: null,
      detail: { decision, final_probability: finalProbability },
    });
    return {
      id: data.id as string,
      taskId,
      adjudicatorId: user.id,
      decision,
      finalProbability,
      rationale,
      adjudicatedAt: data.adjudicated_at as string,
    };
  }

  async listAdjudications(): Promise<Adjudication[]> {
    const { data, error } = await this.client.from("annotation_adjudications").select("*");
    if (error) throw new Error(error.message);
    return (data ?? []).map((row) => ({
      id: row.id as string,
      taskId: row.task_id as string,
      adjudicatorId: row.adjudicator_id as string,
      decision: row.decision as ReviewDecisionValue,
      finalProbability: row.final_probability === null ? null : Number(row.final_probability),
      rationale: row.rationale as string,
      adjudicatedAt: row.adjudicated_at as string,
    }));
  }

  /**
   * Disputes are recorded as audit events rather than as their own table.
   * A dispute is a claim that two reviews disagree; the reviews and the
   * adjudication are the durable records, and duplicating the claim into a
   * mutable table would create a second, disagreeing version of the history.
   */
  async raiseDispute(taskId: string, reason: string): Promise<Dispute> {
    const user = await this.requireUser();
    await this.appendAudit({
      action: "review.dispute",
      resourceType: "annotation_review",
      resourceId: taskId,
      cutoffAt: null,
      snapshotHash: null,
      detail: { reason },
    });
    await this.client.from("annotation_assignments").update({ state: "disputed" }).eq("task_id", taskId);
    return {
      id: `${taskId}-dispute`,
      taskId,
      raisedBy: user.displayName,
      reason,
      raisedAt: new Date().toISOString(),
      resolved: false,
    };
  }

  async listDisputes(): Promise<Dispute[]> {
    const { data, error } = await this.client
      .from("audit_events")
      .select("*")
      .eq("action", "review.dispute")
      .order("occurred_at", { ascending: false });
    if (error) throw new Error(error.message);
    return (data ?? []).map((row) => ({
      id: String(row.id),
      taskId: (row.resource_id ?? "") as string,
      raisedBy: (row.actor_id ?? "unknown") as string,
      reason: ((row.detail ?? {}) as { reason?: string }).reason ?? "",
      raisedAt: row.occurred_at as string,
      resolved: false,
    }));
  }

  /* --------------------------------------------------------- scenarios */

  async listScenarioSessions(): Promise<ScenarioSessionRecord[]> {
    const { data, error } = await this.client
      .from("scenario_sessions")
      .select("*, scenario_inputs(*)")
      .order("updated_at", { ascending: false });
    if (error) throw new Error(error.message);
    return (data ?? []).map((row) => this.mapScenario(row));
  }

  private mapScenario(row: Record<string, unknown>): ScenarioSessionRecord {
    const inputs = (row.scenario_inputs ?? []) as Record<string, unknown>[];
    return {
      id: row.id as string,
      ownerId: row.owner_id as string,
      name: row.name as string,
      forecastId: row.forecast_id as string,
      districtName: row.district_name as string,
      eventFamily: row.event_family as string,
      baselineProbability: Number(row.baseline_probability),
      cutoffAt: row.cutoff_at as string,
      snapshotHash: row.snapshot_hash as string,
      isHypothetical: true,
      updatedAt: row.updated_at as string,
      overrides: inputs.map((i) => ({
        feature: i.feature as string,
        label: i.label as string,
        baselineValue: Number(i.baseline_value),
        hypotheticalValue: Number(i.hypothetical_value),
      })),
    };
  }

  async saveScenarioSession(
    record: Omit<ScenarioSessionRecord, "id" | "ownerId" | "updatedAt">,
  ): Promise<ScenarioSessionRecord> {
    const user = await this.requireUser();
    const { data, error } = await this.client
      .from("scenario_sessions")
      .insert({
        owner_id: user.id,
        name: record.name,
        forecast_id: record.forecastId,
        district_name: record.districtName,
        event_family: record.eventFamily,
        baseline_probability: record.baselineProbability,
        cutoff_at: record.cutoffAt,
        snapshot_hash: record.snapshotHash,
        is_hypothetical: true,
      })
      .select()
      .single();
    if (error) throw new Error(error.message);

    if (record.overrides.length > 0) {
      const { error: inputError } = await this.client.from("scenario_inputs").insert(
        record.overrides.map((o) => ({
          session_id: data.id,
          feature: o.feature,
          label: o.label,
          baseline_value: o.baselineValue,
          hypothetical_value: o.hypotheticalValue,
        })),
      );
      if (inputError) throw new Error(inputError.message);
    }

    await this.appendAudit({
      action: "scenario.save",
      resourceType: "scenario_session",
      resourceId: data.id as string,
      cutoffAt: record.cutoffAt,
      snapshotHash: record.snapshotHash,
      detail: { forecast_id: record.forecastId, is_hypothetical: true },
    });
    return { ...record, isHypothetical: true, id: data.id as string, ownerId: user.id, updatedAt: data.updated_at as string };
  }

  async getScenarioSession(id: string): Promise<ScenarioSessionRecord | null> {
    const { data, error } = await this.client
      .from("scenario_sessions")
      .select("*, scenario_inputs(*)")
      .eq("id", id)
      .maybeSingle();
    if (error) throw new Error(error.message);
    return data ? this.mapScenario(data) : null;
  }

  /* ----------------------------------------------------------- exports */

  async recordExport(record: Omit<ExportRecord, "id" | "actorId" | "createdAt">): Promise<void> {
    const user = await this.requireUser();
    const { error } = await this.client.from("export_records").insert({
      actor_id: user.id,
      export_name: record.exportName,
      format: record.format,
      row_count: record.rowCount,
      cutoff_at: record.cutoffAt,
      snapshot_hash: record.snapshotHash,
      data_mode: record.dataMode,
      is_hypothetical: record.isHypothetical,
    });
    if (error) throw new Error(error.message);
    await this.appendAudit({
      action: "export.create",
      resourceType: "export",
      resourceId: record.exportName,
      cutoffAt: record.cutoffAt,
      snapshotHash: record.snapshotHash,
      detail: { format: record.format, row_count: record.rowCount, is_hypothetical: record.isHypothetical },
    });
  }

  async listExports(): Promise<ExportRecord[]> {
    const { data, error } = await this.client
      .from("export_records")
      .select("*")
      .order("created_at", { ascending: false });
    if (error) throw new Error(error.message);
    return (data ?? []).map((row) => ({
      id: row.id as string,
      actorId: row.actor_id as string,
      exportName: row.export_name as string,
      format: row.format as "csv" | "json",
      rowCount: row.row_count as number,
      cutoffAt: row.cutoff_at as string,
      snapshotHash: row.snapshot_hash as string,
      dataMode: row.data_mode as "live" | "synthetic",
      isHypothetical: row.is_hypothetical as boolean,
      createdAt: row.created_at as string,
    }));
  }

  /* ------------------------------------------------------------- audit */

  async appendAudit(
    event: Omit<AuditEvent, "id" | "actorId" | "actorEmail" | "actorRole" | "occurredAt" | "prevHash" | "entryHash">,
  ): Promise<void> {
    // prev_hash and entry_hash are set by the audit_chain_link() trigger. The
    // client deliberately cannot supply them: a caller that chooses its own
    // chain link can forge a consistent-looking history.
    const { error } = await this.client.from("audit_events").insert({
      action: event.action,
      resource_type: event.resourceType,
      resource_id: event.resourceId,
      cutoff_at: event.cutoffAt,
      snapshot_hash: event.snapshotHash,
      detail: event.detail,
    });
    if (error) throw new Error(error.message);
  }

  async listAudit(): Promise<AuditEvent[]> {
    const { data, error } = await this.client
      .from("audit_events")
      .select("*")
      .order("occurred_at", { ascending: false })
      .limit(500);
    if (error) throw new Error(error.message);
    return (data ?? []).map((row) => ({
      id: String(row.id),
      actorId: (row.actor_id ?? null) as string | null,
      actorEmail: null,
      actorRole: (row.actor_role ?? null) as AppRole | null,
      action: row.action as string,
      resourceType: row.resource_type as string,
      resourceId: (row.resource_id ?? null) as string | null,
      cutoffAt: (row.cutoff_at ?? null) as string | null,
      snapshotHash: (row.snapshot_hash ?? null) as string | null,
      detail: (row.detail ?? {}) as Record<string, unknown>,
      occurredAt: row.occurred_at as string,
      prevHash: (row.prev_hash ?? null) as string | null,
      entryHash: row.entry_hash as string,
    }));
  }

  async verifyAuditChain(): Promise<{ ok: boolean; brokenAt: string | null }> {
    // Verification runs in the database, over rows the client never sees.
    const { data, error } = await this.client.rpc("verify_audit_chain");
    if (error) throw new Error(error.message);
    const broken = ((data ?? []) as { id: number; ok: boolean }[]).find((r) => !r.ok);
    return { ok: !broken, brokenAt: broken ? String(broken.id) : null };
  }

  /* -------------------------------------------------------------- admin */

  async listUsers(): Promise<CloudUser[]> {
    const [{ data: profiles, error }, { data: roles }] = await Promise.all([
      this.client.from("profiles").select("id, display_name"),
      this.client.from("user_roles").select("user_id, role"),
    ]);
    if (error) throw new Error(error.message);
    const byUser = new Map<string, AppRole[]>();
    for (const row of (roles ?? []) as { user_id: string; role: AppRole }[]) {
      byUser.set(row.user_id, [...(byUser.get(row.user_id) ?? []), row.role]);
    }
    return ((profiles ?? []) as { id: string; display_name: string }[]).map((p) => ({
      id: p.id,
      email: "",
      displayName: p.display_name,
      roles: byUser.get(p.id) ?? [],
    }));
  }

  async grantRole(userId: string, role: AppRole): Promise<void> {
    const user = await this.requireUser();
    const { error } = await this.client
      .from("user_roles")
      .insert({ user_id: userId, role, granted_by: user.id });
    if (error) throw new Error(error.message);
    await this.appendAudit({
      action: "role.grant", resourceType: "user_role", resourceId: userId,
      cutoffAt: null, snapshotHash: null, detail: { role },
    });
  }

  async revokeRole(userId: string, role: AppRole): Promise<void> {
    const { error } = await this.client
      .from("user_roles")
      .delete()
      .eq("user_id", userId)
      .eq("role", role);
    if (error) throw new Error(error.message);
    await this.appendAudit({
      action: "role.revoke", resourceType: "user_role", resourceId: userId,
      cutoffAt: null, snapshotHash: null, detail: { role },
    });
  }

  private async requireUser(): Promise<CloudUser> {
    const user = await this.getCurrentUser();
    if (!user) throw new Error("You must be signed in.");
    return user;
  }
}
