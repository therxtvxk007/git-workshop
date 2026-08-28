/**
 * The persistence contract.
 *
 * Two backends implement it: `LocalCloudBackend` (browser storage, so the
 * console runs with no credentials at all) and `SupabaseCloudBackend` (the
 * Postgres schema in supabase/migrations).
 *
 * The interface is written so the *database* enforces the rules. The local
 * backend reimplements them faithfully, but its docstrings say plainly that it
 * is a development convenience: a rule enforced only in the browser is not
 * enforced. See docs/SECURITY_ROLES.md.
 */

export type AppRole = "administrator" | "analyst" | "reviewer" | "viewer";

export const ROLE_ORDER: AppRole[] = ["viewer", "reviewer", "analyst", "administrator"];

export interface CloudUser {
  id: string;
  email: string;
  displayName: string;
  roles: AppRole[];
}

export interface SavedView {
  id: string;
  name: string;
  route: string;
  filters: Record<string, unknown>;
  cutoffAt: string;
  snapshotHash: string;
  isShared: boolean;
  ownerId: string;
  updatedAt: string;
}

export interface AuditEvent {
  id: string;
  actorId: string | null;
  actorEmail: string | null;
  actorRole: AppRole | null;
  action: string;
  resourceType: string;
  resourceId: string | null;
  cutoffAt: string | null;
  snapshotHash: string | null;
  detail: Record<string, unknown>;
  occurredAt: string;
  prevHash: string | null;
  entryHash: string;
}

export type ReviewDecisionValue = "accept" | "correct" | "reject";

export interface ReviewSubmission {
  taskId: string;
  decision: ReviewDecisionValue;
  correctedProbability: number | null;
  rationale: string;
  evidenceIds: string[];
  sawSuggestion: boolean;
  timeSpentSeconds: number;
}

export interface StoredReview extends ReviewSubmission {
  id: string;
  reviewerId: string;
  reviewerLabel: string;
  submittedAt: string;
}

export interface Adjudication {
  id: string;
  taskId: string;
  adjudicatorId: string;
  decision: ReviewDecisionValue;
  finalProbability: number | null;
  rationale: string;
  adjudicatedAt: string;
}

export interface Dispute {
  id: string;
  taskId: string;
  raisedBy: string;
  reason: string;
  raisedAt: string;
  resolved: boolean;
}

export interface ScenarioSessionRecord {
  id: string;
  ownerId: string;
  name: string;
  forecastId: string;
  districtName: string;
  eventFamily: string;
  baselineProbability: number;
  cutoffAt: string;
  snapshotHash: string;
  isHypothetical: true;
  updatedAt: string;
  overrides: {
    feature: string;
    label: string;
    baselineValue: number;
    hypotheticalValue: number;
  }[];
}

export interface ExportRecord {
  id: string;
  actorId: string;
  exportName: string;
  format: "csv" | "json";
  rowCount: number;
  cutoffAt: string;
  snapshotHash: string;
  dataMode: "live" | "synthetic";
  isHypothetical: boolean;
  createdAt: string;
}

export interface CloudBackend {
  readonly kind: "local" | "supabase";

  getCurrentUser(): Promise<CloudUser | null>;
  onAuthChange(listener: (user: CloudUser | null) => void): () => void;
  signIn(email: string, password: string): Promise<CloudUser>;
  signUp(email: string, password: string, displayName: string): Promise<CloudUser>;
  signOut(): Promise<void>;
  /** Bearer token for the REST adapter, or null when there is no session. */
  getAccessToken(): Promise<string | null>;

  listSavedViews(): Promise<SavedView[]>;
  saveView(view: Omit<SavedView, "id" | "ownerId" | "updatedAt">): Promise<SavedView>;
  deleteView(id: string): Promise<void>;

  /** Blinded: peers' reviews are withheld until the caller has submitted. */
  listReviews(taskId: string): Promise<StoredReview[]>;
  submitReview(submission: ReviewSubmission): Promise<StoredReview>;
  adjudicate(taskId: string, decision: ReviewDecisionValue, finalProbability: number | null, rationale: string): Promise<Adjudication>;
  listAdjudications(): Promise<Adjudication[]>;
  raiseDispute(taskId: string, reason: string): Promise<Dispute>;
  listDisputes(): Promise<Dispute[]>;

  listScenarioSessions(): Promise<ScenarioSessionRecord[]>;
  saveScenarioSession(record: Omit<ScenarioSessionRecord, "id" | "ownerId" | "updatedAt">): Promise<ScenarioSessionRecord>;
  getScenarioSession(id: string): Promise<ScenarioSessionRecord | null>;

  recordExport(record: Omit<ExportRecord, "id" | "actorId" | "createdAt">): Promise<void>;
  listExports(): Promise<ExportRecord[]>;

  appendAudit(event: Omit<AuditEvent, "id" | "actorId" | "actorEmail" | "actorRole" | "occurredAt" | "prevHash" | "entryHash">): Promise<void>;
  listAudit(): Promise<AuditEvent[]>;
  /** Recomputes the chain and reports the first broken link, if any. */
  verifyAuditChain(): Promise<{ ok: boolean; brokenAt: string | null }>;

  listUsers(): Promise<CloudUser[]>;
  grantRole(userId: string, role: AppRole): Promise<void>;
  revokeRole(userId: string, role: AppRole): Promise<void>;
}
