import { useState } from "react";
import { Card, CopyChip, Callout } from "@/components/ui/primitives";
import { MetricGrid } from "@/components/charts/MetricGrid";
import { ErrorState, LoadingState } from "@/components/states/StateViews";
import { formatUtc, shortHash } from "@/lib/format";
import { useBacktestRuns, useModelArtifacts, useRunLineage } from "@/lib/queries";

const KIND_LABELS: Record<string, string> = {
  generator: "Generator",
  calibrator: "Calibrator",
  risk_controller: "Risk controller",
  extractor: "Extractor",
  matcher: "Outcome matcher",
};

export function Models() {
  const artifacts = useModelArtifacts();
  const runs = useBacktestRuns();
  const [runId, setRunId] = useState<string | undefined>(undefined);
  const lineage = useRunLineage(runId ?? runs.data?.[0]?.run_id);

  if (artifacts.isLoading) return <LoadingState label="Loading model artefacts" />;
  if (artifacts.error) return <ErrorState error={artifacts.error} />;

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-lg font-semibold">Models</h1>
        <p className="mt-1 max-w-prose text-sm muted">
          Every artefact that contributed to a forecast, with the snapshot it was trained on and a
          plain statement of what it cannot do.
        </p>
      </header>

      <Callout title="Placeholders are labelled as placeholders">
        Two of the components below are deliberately not implementations: the calibrator passes raw
        output through unchanged, and the risk controller applies fixed thresholds. They are listed
        here rather than omitted, because an absent component is easy to mistake for a working one.
      </Callout>

      <div className="grid gap-3 lg:grid-cols-2">
        {(artifacts.data ?? []).map((artifact) => (
          <Card
            key={artifact.artifact_id}
            title={artifact.name}
            subtitle={`${KIND_LABELS[artifact.kind] ?? artifact.kind} · ${artifact.version}`}
          >
            <div className="flex flex-wrap gap-1.5">
              <CopyChip label="artifact" value={artifact.artifact_id} />
              <CopyChip label="code" value={artifact.code_version} />
              <CopyChip label="config" value={artifact.config_hash} />
              {artifact.training_snapshot_hash ? (
                <CopyChip label="trained on" value={artifact.training_snapshot_hash} />
              ) : null}
            </div>

            <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
              <div>
                <dt className="label">Trained</dt>
                <dd>{artifact.trained_at ? formatUtc(artifact.trained_at) : "not trained (rule-based)"}</dd>
              </div>
              <div>
                <dt className="label">Parents</dt>
                <dd className="text-2xs">
                  {artifact.parent_artifact_ids.length ? artifact.parent_artifact_ids.join(", ") : "none"}
                </dd>
              </div>
            </dl>

            {artifact.metrics.length > 0 ? (
              <div className="mt-3">
                <MetricGrid metrics={artifact.metrics} />
              </div>
            ) : null}

            <div className="mt-3 rounded border border-uncertainty-400/40 bg-uncertainty-400/10 px-3 py-2">
              <p className="label">Stated limitations</p>
              <p className="mt-1 text-sm">{artifact.limitations}</p>
            </div>
          </Card>
        ))}
      </div>

      <Card title="Run lineage" subtitle="Snapshot → run → artefacts">
        {runs.data && runs.data.length > 0 ? (
          <div className="mb-3 max-w-sm">
            <label className="label" htmlFor="lineage-run">Run</label>
            <select
              id="lineage-run"
              className="field mt-1"
              value={runId ?? runs.data[0]!.run_id}
              onChange={(e) => setRunId(e.target.value)}
            >
              {runs.data.map((run) => (
                <option key={run.run_id} value={run.run_id}>{run.label}</option>
              ))}
            </select>
          </div>
        ) : null}

        {lineage.isLoading ? <LoadingState label="Loading lineage" /> : null}
        {lineage.error ? <ErrorState error={lineage.error} /> : null}

        {lineage.data ? (
          <ol className="space-y-2">
            {lineage.data.nodes.map((node) => {
              const inbound = lineage.data.edges.filter((edge) => edge.to === node.id);
              return (
                <li key={node.id} className="rounded border border-[rgb(var(--border))] p-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-sm font-medium">{node.label}</span>
                    <span className="chip">{node.kind}</span>
                  </div>
                  <p className="mt-1 text-2xs muted">
                    {node.at ? formatUtc(node.at) : "no timestamp"} ·{" "}
                    <span className="font-mono">{shortHash(node.id, 18)}</span>
                  </p>
                  {inbound.length > 0 ? (
                    <p className="mt-1 text-2xs muted">
                      ← {inbound.map((edge) => `${edge.from} (${edge.label})`).join(", ")}
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ol>
        ) : null}
      </Card>
    </div>
  );
}
