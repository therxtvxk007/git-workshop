import { Link } from "react-router-dom";
import { apiMode } from "@/lib/api/client";
import { cloudIsLocal } from "@/lib/cloud";
import { formatUtc, shortHash } from "@/lib/format";
import { EVENT_FAMILY_LABELS } from "@/lib/format";
import type { SnapshotInfo } from "@/lib/api/types";
import { useSession } from "@/components/SessionProvider";

/**
 * The permanent context strip.
 *
 * Cutoff, event family, snapshot and data mode are here on every route because
 * every number in this console is meaningless without them. "62%" is not a
 * fact; "62% for this district, at this cutoff, from this snapshot" is.
 */
export function TopBar({
  snapshot,
  eventFamily,
  onToggleSidebar,
  onToggleTheme,
  dark,
}: {
  snapshot: SnapshotInfo | undefined;
  eventFamily: string | null;
  onToggleSidebar: () => void;
  onToggleTheme: () => void;
  dark: boolean;
}) {
  const { user, signOut } = useSession();
  const live = apiMode.mode === "rest";

  return (
    <header className="sticky top-0 z-30 border-b border-[rgb(var(--border))] bg-[rgb(var(--surface-raised))]">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2">
        <button
          type="button"
          className="btn px-2 py-1 no-print"
          onClick={onToggleSidebar}
          aria-label="Toggle navigation"
        >
          ☰
        </button>

        <Link to="/" className="text-sm font-semibold tracking-tight">
          Pramaan-X <span className="muted font-normal">Analyst Console</span>
        </Link>

        <div className="flex flex-wrap items-center gap-2 text-2xs">
          <span className="chip" title="All timestamps in this console are UTC.">
            <span className="muted">cutoff</span>
            {snapshot ? formatUtc(snapshot.cutoff_at) : "—"}
          </span>
          <span className="chip">
            <span className="muted">family</span>
            {eventFamily
              ? (EVENT_FAMILY_LABELS[eventFamily as keyof typeof EVENT_FAMILY_LABELS] ?? eventFamily)
              : "all"}
          </span>
          <span className="chip" title={snapshot?.snapshot_hash}>
            <span className="muted">snapshot</span>
            {snapshot ? shortHash(snapshot.snapshot_hash, 10) : "—"}
          </span>
          <span
            className={`inline-flex items-center rounded-full border px-2 py-0.5 font-semibold uppercase tracking-wide ${
              live
                ? "border-navy-500/50 bg-navy-500/15 text-navy-700 dark:text-navy-200"
                : "border-uncertainty-400/50 bg-uncertainty-400/15 text-uncertainty-700 dark:text-uncertainty-300"
            }`}
            title={apiMode.description}
          >
            {apiMode.label}
          </span>
          {cloudIsLocal ? (
            <span
              className="chip"
              title="No cloud project is configured. Reviews, scenarios and the audit log are stored in this browser only, and none of the database policies are in force."
            >
              local storage
            </span>
          ) : null}
        </div>

        <div className="ml-auto flex items-center gap-2 no-print">
          <button type="button" className="btn px-2 py-1" onClick={onToggleTheme}>
            {dark ? "☀" : "☾"}
            <span className="sr-only">Toggle colour theme</span>
          </button>
          {user ? (
            <div className="flex items-center gap-2">
              <div className="text-right leading-tight">
                <p className="text-xs font-medium">{user.displayName}</p>
                <p className="text-2xs muted">{user.roles.join(", ") || "no role"}</p>
              </div>
              <button type="button" className="btn px-2 py-1" onClick={() => void signOut()}>
                Sign out
              </button>
            </div>
          ) : (
            <Link to="/auth" className="btn-primary px-3 py-1">Sign in</Link>
          )}
        </div>
      </div>
    </header>
  );
}
