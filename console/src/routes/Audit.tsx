import { useEffect, useState } from "react";
import { Card, Callout } from "@/components/ui/primitives";
import { EmptyState, LoadingState } from "@/components/states/StateViews";
import { formatUtc, shortHash } from "@/lib/format";
import { cloud, type AuditEvent } from "@/lib/cloud";

const ACTION_LABELS: Record<string, string> = {
  "review.submit": "Review submitted",
  "review.adjudicate": "Adjudication recorded",
  "review.dispute": "Dispute raised",
  "export.create": "Export produced",
  "role.grant": "Role granted",
  "role.revoke": "Role revoked",
  "scenario.save": "Scenario saved",
};

export function AuditTimeline() {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [chain, setChain] = useState<{ ok: boolean; brokenAt: string | null } | null>(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    void cloud.listAudit().then(setEvents);
    void cloud.verifyAuditChain().then(setChain);
  }, []);

  const filtered = (events ?? []).filter((event) =>
    filter ? `${event.action} ${event.resourceType} ${event.resourceId ?? ""}`.includes(filter) : true,
  );

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-lg font-semibold">Audit</h1>
        <p className="mt-1 max-w-prose text-sm muted">
          Append-only. Each entry hashes the one before it, so a deletion or an edit breaks the
          chain and this page says where.
        </p>
      </header>

      {chain ? (
        chain.ok ? (
          <Callout title="Chain verified">
            Every entry’s hash matches its contents and its predecessor. This proves the log has not
            been altered through the application; it does not prove that nobody with direct database
            access could alter it, which is why the verification is recomputed rather than trusted.
          </Callout>
        ) : (
          <Callout tone="alert" title="Chain broken">
            The hash chain fails at entry <code>{chain.brokenAt}</code>. An entry has been removed
            or modified outside the application. Treat every entry after that point as unverified.
          </Callout>
        )
      ) : null}

      <Card
        title="Timeline"
        actions={
          <input
            className="field w-48"
            type="search"
            aria-label="Filter audit events"
            placeholder="Filter by action"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        }
      >
        {events === null ? (
          <LoadingState label="Loading audit events" />
        ) : filtered.length === 0 ? (
          <EmptyState title="No audit events">
            Reads are not audited. Submitting a review, adjudicating, exporting, saving a scenario
            and changing a role are — an audit log that records page views buries the entries that
            matter.
          </EmptyState>
        ) : (
          <ol className="space-y-2">
            {filtered.map((event) => (
              <li key={event.id} className="rounded border border-[rgb(var(--border))] p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-sm font-medium">
                    {ACTION_LABELS[event.action] ?? event.action}
                  </span>
                  <span className="text-2xs muted">{formatUtc(event.occurredAt, { seconds: true })}</span>
                </div>
                <p className="mt-1 text-2xs muted">
                  {event.actorEmail ?? event.actorId ?? "unknown actor"}
                  {event.actorRole ? ` (${event.actorRole})` : ""} · {event.resourceType}
                  {event.resourceId ? ` · ${event.resourceId}` : ""}
                </p>
                {Object.keys(event.detail).length > 0 ? (
                  <pre className="mt-1 overflow-x-auto rounded bg-[rgb(var(--surface-sunken))] p-2 text-2xs">
                    {JSON.stringify(event.detail)}
                  </pre>
                ) : null}
                <p className="mt-1 font-mono text-2xs muted">
                  prev {event.prevHash ? shortHash(event.prevHash, 12) : "genesis"} → entry{" "}
                  {shortHash(event.entryHash, 12)}
                </p>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}
