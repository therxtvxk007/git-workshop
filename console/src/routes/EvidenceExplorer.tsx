import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Card, Callout } from "@/components/ui/primitives";
import { EvidenceCard } from "@/components/evidence/EvidenceCard";
import { EvidenceDrawer } from "@/components/evidence/EvidenceDrawer";
import { EmptyState, ErrorState, LoadingState } from "@/components/states/StateViews";
import { EVENT_FAMILY_LABELS } from "@/lib/format";
import { useEvidence, useSnapshot } from "@/lib/queries";
import type { EventFamily, EvidenceQuery, Stance } from "@/lib/api/types";

const FAMILIES = Object.keys(EVENT_FAMILY_LABELS) as EventFamily[];

/**
 * Search over the observation ledger.
 *
 * `include_post_cutoff` defaults to off and is a deliberate, labelled opt-in.
 * Browsing post-cutoff material while reasoning about a forecast is how an
 * analyst convinces themselves the model "knew" something it could not have.
 */
export function EvidenceExplorer() {
  const [params, setParams] = useSearchParams();
  const { data: snapshot } = useSnapshot();
  const [openEvidence, setOpenEvidence] = useState<string | null>(params.get("evidenceId"));

  const query: EvidenceQuery = {
    ...(params.get("q") ? { search: params.get("q")! } : {}),
    ...(params.get("family") ? { event_family: params.get("family") as EventFamily } : {}),
    ...(params.get("stance") ? { stance: params.get("stance") as Stance } : {}),
    include_post_cutoff: params.get("post") === "1",
    limit: 60,
  };

  const evidence = useEvidence(query);

  const update = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const open = (id: string | null) => {
    setOpenEvidence(id);
    update("evidenceId", id);
  };

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-lg font-semibold">Evidence explorer</h1>
        <p className="mt-1 max-w-prose text-sm muted">
          Every observation the ingestion layer retained, with its stance, reliability, licence and
          independence cluster. Ten outlets rewriting one wire story are one cluster here, not ten.
        </p>
      </header>

      <Card>
        <div className="grid gap-3 md:grid-cols-4">
          <div className="md:col-span-2">
            <label className="label" htmlFor="ev-search">Search</label>
            <input
              id="ev-search"
              type="search"
              className="field mt-1"
              placeholder="Claim, title or source"
              defaultValue={params.get("q") ?? ""}
              onChange={(e) => update("q", e.target.value || null)}
            />
          </div>
          <div>
            <label className="label" htmlFor="ev-family">Event family</label>
            <select
              id="ev-family"
              className="field mt-1"
              value={params.get("family") ?? ""}
              onChange={(e) => update("family", e.target.value || null)}
            >
              <option value="">All</option>
              {FAMILIES.map((family) => (
                <option key={family} value={family}>{EVENT_FAMILY_LABELS[family]}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="ev-stance">Stance</label>
            <select
              id="ev-stance"
              className="field mt-1"
              value={params.get("stance") ?? ""}
              onChange={(e) => update("stance", e.target.value || null)}
            >
              <option value="">All</option>
              <option value="supports">Supports</option>
              <option value="contradicts">Contradicts</option>
              <option value="context">Context</option>
            </select>
          </div>
        </div>

        <label className="mt-3 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={params.get("post") === "1"}
            onChange={(e) => update("post", e.target.checked ? "1" : null)}
          />
          Include evidence observed after the cutoff
        </label>
        {params.get("post") === "1" ? (
          <Callout tone="uncertainty" title="Post-cutoff evidence is included">
            These items were not available to the model at the cutoff. They are useful for
            retrospective review and must not be used to explain or justify a score the model
            produced without them.
          </Callout>
        ) : null}
      </Card>

      {evidence.isLoading ? <LoadingState label="Searching evidence" /> : null}
      {evidence.error ? <ErrorState error={evidence.error} /> : null}

      {evidence.data ? (
        <>
          <p className="text-2xs muted" aria-live="polite">
            {evidence.data.items.length} shown of {evidence.data.total} matching.
            {evidence.data.withheld > 0
              ? ` ${evidence.data.withheld} withheld by licence — counted, not silently dropped.`
              : ""}
          </p>

          {evidence.data.items.length === 0 ? (
            <EmptyState title="No evidence matches this search">
              The ledger was searched and returned nothing. If a district you expect is missing,
              check data health before concluding there is no signal there.
            </EmptyState>
          ) : (
            <div className="grid gap-2 lg:grid-cols-2">
              {evidence.data.items.map((item) => (
                <EvidenceCard
                  key={item.evidence_id}
                  item={item}
                  cutoffAt={snapshot?.cutoff_at ?? item.first_observed_at}
                  active={openEvidence === item.evidence_id}
                  onOpen={(opened) => open(opened.evidence_id)}
                />
              ))}
            </div>
          )}
        </>
      ) : null}

      <EvidenceDrawer
        evidenceId={openEvidence}
        cutoffAt={snapshot?.cutoff_at ?? ""}
        onClose={() => open(null)}
      />
    </div>
  );
}
