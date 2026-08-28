import { cloud } from "@/lib/cloud";
import type { AppRole } from "@/lib/cloud/types";

/**
 * The audited actions, in one place.
 *
 * Every state-changing thing the console can do goes through a function here,
 * so "what gets audited?" has a single, readable answer instead of being spread
 * across twelve components. Against Postgres these are thin wrappers over
 * inserts whose `prev_hash`/`entry_hash` are computed by a trigger; the client
 * cannot choose its own chain link.
 *
 * Read access is not audited. An audit log that records every page view buries
 * the four actions that matter under ten thousand that do not.
 */

export interface AuditContext {
  cutoffAt: string | null;
  snapshotHash: string | null;
}

export async function auditView(
  resourceType: string,
  resourceId: string,
  context: AuditContext,
  detail: Record<string, unknown> = {},
): Promise<void> {
  // Used only for the handful of reads that are themselves consequential:
  // opening a blinded task, and revealing restricted evidence.
  await cloud.appendAudit({
    action: `${resourceType}.open`,
    resourceType,
    resourceId,
    cutoffAt: context.cutoffAt,
    snapshotHash: context.snapshotHash,
    detail,
  });
}

export async function auditExport(
  name: string,
  format: "csv" | "json",
  rowCount: number,
  context: AuditContext & { dataMode: "live" | "synthetic"; isHypothetical: boolean },
): Promise<void> {
  await cloud.recordExport({
    exportName: name,
    format,
    rowCount,
    cutoffAt: context.cutoffAt ?? "",
    snapshotHash: context.snapshotHash ?? "",
    dataMode: context.dataMode,
    isHypothetical: context.isHypothetical,
  });
}

export async function checkRole(required: AppRole): Promise<boolean> {
  const user = await cloud.getCurrentUser();
  if (!user) return false;
  if (user.roles.includes("administrator")) return true;
  return user.roles.includes(required);
}

/**
 * Whether the UI should offer an action.
 *
 * This is presentation, not security. Hiding a button prevents an unpleasant
 * error message; it does not prevent the action. Every one of these is backed
 * by a policy that refuses the write regardless of what the client renders.
 */
export function canAct(roles: AppRole[], required: AppRole): boolean {
  return roles.includes("administrator") || roles.includes(required);
}
