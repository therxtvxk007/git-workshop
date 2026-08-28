import type { ReactNode } from "react";
import { AccessDeniedError, ApiUnavailableError, MalformedResponseError } from "@/lib/api/errors";

/**
 * The seven states every data surface in this console can be in.
 *
 * They are separate components rather than one `<Empty>` because they mean
 * genuinely different things, and collapsing them is how a console ends up
 * telling an analyst that a district has no risk when in fact the source feeding
 * that district has been down for six days.
 *
 *   Loading      — we are asking
 *   Empty        — we asked, the answer is "none", and that answer is real
 *   Unavailable  — we could not ask, or the engine has not implemented this
 *   Denied       — we asked and are not permitted to know
 *   Malformed    — we asked and got something that violates the contract
 *   Stale        — this is real, but it is older than the active cutoff
 *   Partial      — this is real and incomplete, and here is what is missing
 */

function Frame({
  tone = "neutral",
  icon,
  title,
  children,
  action,
}: {
  tone?: "neutral" | "uncertainty" | "alert";
  icon: string;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const toneClass =
    tone === "alert"
      ? "border-alert-500/40 bg-alert-500/5"
      : tone === "uncertainty"
        ? "border-uncertainty-400/40 bg-uncertainty-400/5"
        : "border-[rgb(var(--border))] bg-[rgb(var(--surface-sunken))]";
  return (
    <div className={`rounded-lg border p-6 text-center ${toneClass}`} role="status">
      <div aria-hidden className="mb-2 text-2xl">{icon}</div>
      <p className="text-sm font-semibold">{title}</p>
      {children ? <div className="mx-auto mt-1 max-w-prose text-sm muted">{children}</div> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="space-y-2 p-4" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{label}</span>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          aria-hidden
          className="h-4 animate-pulse rounded bg-[rgb(var(--surface-sunken))]"
          style={{ width: `${100 - i * 18}%` }}
        />
      ))}
    </div>
  );
}

export function EmptyState({ title = "No matching records", children }: { title?: string; children?: ReactNode }) {
  return (
    <Frame icon="∅" title={title}>
      {children ?? "The query succeeded and returned nothing. This is a real answer, not a failure."}
    </Frame>
  );
}

export function UnavailableState({ error, children }: { error?: unknown; children?: ReactNode }) {
  const endpoint = error instanceof ApiUnavailableError ? error.endpoint : null;
  return (
    <Frame tone="uncertainty" icon="⚠" title="Unavailable">
      {children ?? (
        <>
          <p>
            The engine could not be reached, or has not implemented this endpoint. Nothing is being
            shown in its place — an empty chart here would read as “no risk”.
          </p>
          {endpoint ? <p className="mt-2 font-mono text-2xs">{endpoint}</p> : null}
        </>
      )}
    </Frame>
  );
}

export function DeniedState({ error, children }: { error?: unknown; children?: ReactNode }) {
  const required = error instanceof AccessDeniedError ? error.requiredRole : undefined;
  const resource = error instanceof AccessDeniedError ? error.resource : undefined;
  return (
    <Frame tone="uncertainty" icon="🔒" title="Not permitted">
      {children ?? (
        <>
          <p>
            This record exists, and you are not permitted to see it. It is named here rather than
            hidden, so its absence is not mistaken for its non-existence.
          </p>
          {resource ? <p className="mt-2 font-mono text-2xs">{resource}</p> : null}
          {required ? <p className="mt-1">Requires the <strong>{required}</strong> role.</p> : null}
        </>
      )}
    </Frame>
  );
}

export function MalformedState({ error }: { error?: unknown }) {
  const issues = error instanceof MalformedResponseError ? error.issues : [];
  return (
    <Frame tone="alert" icon="✖" title="Response failed contract validation">
      <p>
        The engine answered, but the payload violates the forecast contract. It is not rendered:
        a probability that failed validation is not safe to display at all.
      </p>
      {issues.length > 0 ? (
        <ul className="mt-3 space-y-1 text-left font-mono text-2xs">
          {issues.slice(0, 8).map((issue) => (
            <li key={issue}>• {issue}</li>
          ))}
          {issues.length > 8 ? <li>• …and {issues.length - 8} more</li> : null}
        </ul>
      ) : null}
    </Frame>
  );
}

export function StaleBanner({ asOf, cutoff }: { asOf: string; cutoff: string }) {
  return (
    <div className="rounded-md border border-uncertainty-400/40 bg-uncertainty-400/10 px-3 py-2 text-sm">
      <strong>Stale.</strong> These values were computed at <span className="font-mono">{asOf}</span>,
      before the active cutoff <span className="font-mono">{cutoff}</span>. They have not been
      recomputed and may not reflect evidence that arrived since.
    </div>
  );
}

export function PartialBanner({ missing, reason }: { missing: string; reason: string }) {
  return (
    <div className="rounded-md border border-uncertainty-400/40 bg-uncertainty-400/10 px-3 py-2 text-sm">
      <strong>Partial.</strong> {missing} is missing from this view. {reason} Absence here is a gap
      in coverage, not an observation of nothing.
    </div>
  );
}

/**
 * Picks the right state for a thrown error.
 *
 * An unrecognised error is shown as "unavailable" rather than swallowed: a
 * blank panel where a chart should be is the failure mode this whole module
 * exists to prevent.
 */
export function ErrorState({ error }: { error: unknown }) {
  if (error instanceof AccessDeniedError) return <DeniedState error={error} />;
  if (error instanceof MalformedResponseError) return <MalformedState error={error} />;
  if (error instanceof ApiUnavailableError) return <UnavailableState error={error} />;
  return (
    <UnavailableState>
      <p>An unexpected error prevented this from loading.</p>
      <p className="mt-2 font-mono text-2xs">{error instanceof Error ? error.message : String(error)}</p>
    </UnavailableState>
  );
}
