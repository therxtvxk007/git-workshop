import { Drawer, DefinitionList, Callout } from "@/components/ui/primitives";
import { SpanHighlight } from "./EvidenceCard";
import { DeniedState, ErrorState, LoadingState } from "@/components/states/StateViews";
import { useEvidenceItem } from "@/lib/queries";
import { formatProbability, formatUtc } from "@/lib/format";
import { AccessDeniedError } from "@/lib/api/errors";

export function EvidenceDrawer({
  evidenceId,
  cutoffAt,
  onClose,
}: {
  evidenceId: string | null;
  cutoffAt: string;
  onClose: () => void;
}) {
  const { data, error, isLoading } = useEvidenceItem(evidenceId ?? undefined);

  return (
    <Drawer open={!!evidenceId} title="Evidence detail" onClose={onClose}>
      {isLoading ? <LoadingState label="Loading evidence" /> : null}
      {error instanceof AccessDeniedError ? (
        <DeniedState error={error}>
          <p>
            This item exists and is part of the evidence set behind the forecast, but its licence
            does not permit redistribution through this console.
          </p>
          <p className="mt-2">
            It is named rather than removed: an evidence list that silently drops restricted items
            understates how much the model actually had.
          </p>
        </DeniedState>
      ) : error ? (
        <ErrorState error={error} />
      ) : null}

      {data ? (
        <div className="space-y-4">
          <div>
            <h3 className="text-sm font-semibold">{data.title}</h3>
            <p className="mt-1 text-sm">{data.claim}</p>
          </div>

          {data.post_cutoff ? (
            <Callout tone="uncertainty" title="Observed after the cutoff">
              This item arrived after the forecast cutoff. The model did not use it and could not
              have. It is shown so you can see what the model was missing, never as a justification
              for the score.
            </Callout>
          ) : null}

          {data.syndication_of ? (
            <Callout tone="uncertainty" title="Syndicated">
              This is a rewrite of <code>{data.syndication_of}</code>. It shares an independence
              cluster with {data.cluster_size - 1} other item
              {data.cluster_size - 1 === 1 ? "" : "s"} and is not additional evidence.
            </Callout>
          ) : null}

          <div>
            <p className="label">Extracted span</p>
            <div className="mt-1 rounded border border-[rgb(var(--border))] bg-[rgb(var(--surface-sunken))] p-3">
              <SpanHighlight item={data} />
            </div>
          </div>

          <DefinitionList
            items={[
              { label: "Source", value: data.source_name },
              { label: "Licence", value: data.license },
              { label: "Stance", value: data.stance },
              { label: "Modality", value: data.modality },
              { label: "Reliability", value: formatProbability(data.reliability) },
              { label: "Independence cluster", value: data.independence_cluster ?? "singleton" },
              { label: "Published", value: formatUtc(data.published_at) },
              { label: "First observed", value: formatUtc(data.first_observed_at) },
              { label: "Retrieved", value: formatUtc(data.retrieved_at) },
              { label: "Active cutoff", value: formatUtc(cutoffAt) },
              { label: "Observation id", value: <code className="text-2xs">{data.observation_id}</code> },
              {
                label: "Link",
                value: data.url ? (
                  <a className="underline" href={data.url} rel="noreferrer noopener" target="_blank">
                    {new URL(data.url).hostname}
                  </a>
                ) : (
                  "not redistributable"
                ),
              },
            ]}
          />
        </div>
      ) : null}
    </Drawer>
  );
}
