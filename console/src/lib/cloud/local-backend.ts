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
import { nowUtc } from "@/lib/format";

/**
 * A browser-storage backend, so the console is runnable with no cloud project.
 *
 * It reproduces the Postgres rules — blinding, immutable reviews, the audit
 * hash chain, role gating — as faithfully as a client can. That faithfulness is
 * for *demonstration*, not for security: everything here is editable from the
 * browser's devtools in about four seconds.
 *
 * The real guarantees are in supabase/migrations, tested by
 * supabase/tests/01_rls_test.sql. This file exists so a reader can click
 * through the workflow before standing up a database, and it says so in the
 * top bar whenever it is active.
 */

const NS = "pramaanx.console.v1";

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(`${NS}.${key}`);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write<T>(key: string, value: T): void {
  try {
    localStorage.setItem(`${NS}.${key}`, JSON.stringify(value));
  } catch {
    // A full or disabled storage quota must not take the console down; the
    // session simply becomes non-persistent.
  }
}

function uid(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** FNV-1a. Not cryptographic; enough to show a chain break in the demo. */
async function hash(input: string): Promise<string> {
  if (globalThis.crypto?.subtle) {
    const bytes = new TextEncoder().encode(input);
    const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }
  let h = 0x811c9dc5;
  for (const ch of input) {
    h ^= ch.charCodeAt(0);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}

interface StoredUser extends CloudUser {
  password: string;
}

/** Three signed-in identities, so role gating is visible without sign-up. */
const SEED_USERS: StoredUser[] = [
  { id: "u-admin", email: "admin@demo.invalid", displayName: "Demo Administrator", roles: ["administrator", "analyst", "reviewer", "viewer"], password: "demo" },
  { id: "u-analyst", email: "analyst@demo.invalid", displayName: "Demo Analyst", roles: ["analyst", "viewer"], password: "demo" },
  { id: "u-reviewer", email: "reviewer@demo.invalid", displayName: "Demo Reviewer", roles: ["reviewer", "viewer"], password: "demo" },
  { id: "u-peer", email: "peer@demo.invalid", displayName: "Second Reviewer", roles: ["reviewer", "viewer"], password: "demo" },
];

export class LocalCloudBackend implements CloudBackend {
  readonly kind = "local" as const;
  private listeners = new Set<(user: CloudUser | null) => void>();

  private users(): StoredUser[] {
    const stored = read<StoredUser[]>("users", []);
    return stored.length ? stored : SEED_USERS;
  }

  private currentId(): string | null {
    return read<string | null>("session", null);
  }

  private strip(user: StoredUser): CloudUser {
    const { password: _password, ...rest } = user;
    return rest;
  }

  private emit(user: CloudUser | null) {
    for (const listener of this.listeners) listener(user);
  }

  async getCurrentUser(): Promise<CloudUser | null> {
    const id = this.currentId();
    const user = this.users().find((u) => u.id === id);
    return user ? this.strip(user) : null;
  }

  onAuthChange(listener: (user: CloudUser | null) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async signIn(email: string, password: string): Promise<CloudUser> {
    const user = this.users().find((u) => u.email.toLowerCase() === email.trim().toLowerCase());
    if (!user || user.password !== password) throw new Error("Incorrect email or password.");
    write("session", user.id);
    const stripped = this.strip(user);
    this.emit(stripped);
    return stripped;
  }

  async signUp(email: string, password: string, displayName: string): Promise<CloudUser> {
    const users = this.users();
    if (users.some((u) => u.email.toLowerCase() === email.trim().toLowerCase())) {
      throw new Error("An account with that email already exists.");
    }
    // New accounts get `viewer` and nothing else, mirroring handle_new_user().
    const user: StoredUser = {
      id: `u-${uid()}`,
      email: email.trim(),
      displayName: displayName.trim() || email.split("@")[0] || "Analyst",
      roles: ["viewer"],
      password,
    };
    write("users", [...users, user]);
    write("session", user.id);
    const stripped = this.strip(user);
    this.emit(stripped);
    return stripped;
  }

  async signOut(): Promise<void> {
    write("session", null);
    this.emit(null);
  }

  async getAccessToken(): Promise<string | null> {
    return null; // No real tokens exist in local mode.
  }

  /* ------------------------------------------------------------ views */

  async listSavedViews(): Promise<SavedView[]> {
    const me = await this.getCurrentUser();
    return read<SavedView[]>("views", []).filter((v) => v.isShared || v.ownerId === me?.id);
  }

  async saveView(view: Omit<SavedView, "id" | "ownerId" | "updatedAt">): Promise<SavedView> {
    const me = await this.requireUser();
    const record: SavedView = { ...view, id: uid(), ownerId: me.id, updatedAt: nowUtc().toISOString() };
    write("views", [...read<SavedView[]>("views", []), record]);
    return record;
  }

  async deleteView(id: string): Promise<void> {
    const me = await this.requireUser();
    write(
      "views",
      read<SavedView[]>("views", []).filter(
        (v) => v.id !== id || (v.ownerId !== me.id && !me.roles.includes("administrator")),
      ),
    );
  }

  /* ----------------------------------------------------------- review */

  async listReviews(taskId: string): Promise<StoredReview[]> {
    const me = await this.getCurrentUser();
    const all = read<StoredReview[]>("reviews", []).filter((r) => r.taskId === taskId);
    if (!me) return [];
    if (me.roles.includes("administrator")) return all;
    const mine = all.filter((r) => r.reviewerId === me.id);
    // The blinding rule, mirrored: peers appear only once you have submitted.
    return mine.length > 0 ? all : mine;
  }

  async submitReview(submission: ReviewSubmission): Promise<StoredReview> {
    const me = await this.requireUser();
    if (!me.roles.includes("reviewer") && !me.roles.includes("administrator")) {
      throw new Error("Submitting a review requires the reviewer role.");
    }
    const all = read<StoredReview[]>("reviews", []);
    if (all.some((r) => r.taskId === submission.taskId && r.reviewerId === me.id)) {
      // Mirrors the missing UPDATE policy: a submitted review is final.
      throw new Error("You have already submitted a review for this task. Reviews are immutable.");
    }
    const record: StoredReview = {
      ...submission,
      id: uid(),
      reviewerId: me.id,
      reviewerLabel: me.displayName,
      submittedAt: nowUtc().toISOString(),
    };
    write("reviews", [...all, record]);
    await this.appendAudit({
      action: "review.submit",
      resourceType: "annotation_review",
      resourceId: submission.taskId,
      cutoffAt: null,
      snapshotHash: null,
      detail: { decision: submission.decision, saw_suggestion: submission.sawSuggestion },
    });
    return record;
  }

  async adjudicate(
    taskId: string,
    decision: ReviewDecisionValue,
    finalProbability: number | null,
    rationale: string,
  ): Promise<Adjudication> {
    const me = await this.requireUser();
    if (!me.roles.includes("administrator")) throw new Error("Adjudication requires the administrator role.");
    const record: Adjudication = {
      id: uid(),
      taskId,
      adjudicatorId: me.id,
      decision,
      finalProbability,
      rationale,
      adjudicatedAt: nowUtc().toISOString(),
    };
    write("adjudications", [...read<Adjudication[]>("adjudications", []), record]);
    await this.appendAudit({
      action: "review.adjudicate",
      resourceType: "annotation_adjudication",
      resourceId: taskId,
      cutoffAt: null,
      snapshotHash: null,
      detail: { decision, final_probability: finalProbability },
    });
    return record;
  }

  async listAdjudications(): Promise<Adjudication[]> {
    return read<Adjudication[]>("adjudications", []);
  }

  async raiseDispute(taskId: string, reason: string): Promise<Dispute> {
    const me = await this.requireUser();
    const record: Dispute = {
      id: uid(),
      taskId,
      raisedBy: me.displayName,
      reason,
      raisedAt: nowUtc().toISOString(),
      resolved: false,
    };
    write("disputes", [...read<Dispute[]>("disputes", []), record]);
    await this.appendAudit({
      action: "review.dispute",
      resourceType: "annotation_review",
      resourceId: taskId,
      cutoffAt: null,
      snapshotHash: null,
      detail: { reason },
    });
    return record;
  }

  async listDisputes(): Promise<Dispute[]> {
    return read<Dispute[]>("disputes", []);
  }

  /* --------------------------------------------------------- scenarios */

  async listScenarioSessions(): Promise<ScenarioSessionRecord[]> {
    const me = await this.getCurrentUser();
    return read<ScenarioSessionRecord[]>("scenarios", []).filter((s) => s.ownerId === me?.id);
  }

  async saveScenarioSession(
    record: Omit<ScenarioSessionRecord, "id" | "ownerId" | "updatedAt">,
  ): Promise<ScenarioSessionRecord> {
    const me = await this.requireUser();
    const stored: ScenarioSessionRecord = {
      ...record,
      isHypothetical: true,
      id: uid(),
      ownerId: me.id,
      updatedAt: nowUtc().toISOString(),
    };
    write("scenarios", [...read<ScenarioSessionRecord[]>("scenarios", []), stored]);
    await this.appendAudit({
      action: "scenario.save",
      resourceType: "scenario_session",
      resourceId: stored.id,
      cutoffAt: record.cutoffAt,
      snapshotHash: record.snapshotHash,
      detail: { forecast_id: record.forecastId, is_hypothetical: true },
    });
    return stored;
  }

  async getScenarioSession(id: string): Promise<ScenarioSessionRecord | null> {
    return read<ScenarioSessionRecord[]>("scenarios", []).find((s) => s.id === id) ?? null;
  }

  /* ----------------------------------------------------------- exports */

  async recordExport(record: Omit<ExportRecord, "id" | "actorId" | "createdAt">): Promise<void> {
    const me = await this.getCurrentUser();
    const stored: ExportRecord = {
      ...record,
      id: uid(),
      actorId: me?.id ?? "anonymous",
      createdAt: nowUtc().toISOString(),
    };
    write("exports", [...read<ExportRecord[]>("exports", []), stored]);
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
    return read<ExportRecord[]>("exports", []);
  }

  /* ------------------------------------------------------------- audit */

  async appendAudit(
    event: Omit<AuditEvent, "id" | "actorId" | "actorEmail" | "actorRole" | "occurredAt" | "prevHash" | "entryHash">,
  ): Promise<void> {
    const me = await this.getCurrentUser();
    const events = read<AuditEvent[]>("audit", []);
    const prev = events.length > 0 ? events[events.length - 1]!.entryHash : null;
    const occurredAt = nowUtc().toISOString();
    const entryHash = await hash(
      [prev ?? "", me?.id ?? "", event.action, event.resourceType, event.resourceId ?? "",
       event.snapshotHash ?? "", JSON.stringify(event.detail), occurredAt].join("|"),
    );
    const record: AuditEvent = {
      ...event,
      id: uid(),
      actorId: me?.id ?? null,
      actorEmail: me?.email ?? null,
      actorRole: me?.roles[0] ?? null,
      occurredAt,
      prevHash: prev,
      entryHash,
    };
    write("audit", [...events, record]);
  }

  async listAudit(): Promise<AuditEvent[]> {
    return [...read<AuditEvent[]>("audit", [])].reverse();
  }

  async verifyAuditChain(): Promise<{ ok: boolean; brokenAt: string | null }> {
    const events = read<AuditEvent[]>("audit", []);
    let prev: string | null = null;
    for (const event of events) {
      const expected = await hash(
        [prev ?? "", event.actorId ?? "", event.action, event.resourceType, event.resourceId ?? "",
         event.snapshotHash ?? "", JSON.stringify(event.detail), event.occurredAt].join("|"),
      );
      if (event.prevHash !== prev || event.entryHash !== expected) {
        return { ok: false, brokenAt: event.id };
      }
      prev = event.entryHash;
    }
    return { ok: true, brokenAt: null };
  }

  /* -------------------------------------------------------------- admin */

  async listUsers(): Promise<CloudUser[]> {
    return this.users().map((u) => this.strip(u));
  }

  async grantRole(userId: string, role: AppRole): Promise<void> {
    await this.requireAdmin();
    const users = this.users().map((u) =>
      u.id === userId && !u.roles.includes(role) ? { ...u, roles: [...u.roles, role] } : u,
    );
    write("users", users);
    await this.appendAudit({
      action: "role.grant", resourceType: "user_role", resourceId: userId,
      cutoffAt: null, snapshotHash: null, detail: { role },
    });
  }

  async revokeRole(userId: string, role: AppRole): Promise<void> {
    await this.requireAdmin();
    const users = this.users().map((u) =>
      u.id === userId ? { ...u, roles: u.roles.filter((r) => r !== role) } : u,
    );
    write("users", users);
    await this.appendAudit({
      action: "role.revoke", resourceType: "user_role", resourceId: userId,
      cutoffAt: null, snapshotHash: null, detail: { role },
    });
  }

  private async requireUser(): Promise<CloudUser> {
    const me = await this.getCurrentUser();
    if (!me) throw new Error("You must be signed in.");
    return me;
  }

  private async requireAdmin(): Promise<CloudUser> {
    const me = await this.requireUser();
    if (!me.roles.includes("administrator")) throw new Error("This action requires the administrator role.");
    return me;
  }
}
