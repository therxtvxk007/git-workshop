import { useSearchParams } from "react-router-dom";
import { Card, Callout } from "@/components/ui/primitives";
import { MetricGrid, ArmComparison } from "@/components/charts/MetricGrid";
import {
  AbstentionRiskCurve,
  BudgetRecallCurve,
  PRCurve,
  ReliabilityDiagram,
} from "@/components/charts/EvaluationCharts";
import { ErrorBoundary } from "@/components/states/ErrorBoundary";
import { EmptyState, ErrorState, LoadingState } from "@/components/states/StateViews";
import { formatCount, formatUtc, shortHash } from "@/lib/format";
import { useBacktestRun, useBacktestRuns } from "@/lib/queries";

export function Backtests() {
  const [params, setParams] = useSearchParams();
  const runs = useBacktestRuns();
  const runId = params.get("run") ?? runs.data?.[0]?.run_id;
  const compareId = params.get("compare") ?? undefined;

  const run = useBacktestRun(runId);
  const comparison = useBacktestRun(compareId);

  const update = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-lg font-semibold">Backtests</h1>
        <p className="mt-1 max-w-prose text-sm muted">
          Rolling-origin evaluation. Every fold is scored on a snapshot built at its own cutoff, so
          nothing here is fitted on data it later predicts.
        </p>
      </header>

      {runs.isLoading ? <LoadingState label="Loading runs" /> : null}
      {runs.error ? <ErrorState error={runs.error} /> : null}

      {runs.data ? (
        runs.data.length === 0 ? (
          <EmptyState title="No evaluation runs are available" />
        ) : (
          <Card>
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <label className="label" htmlFor="run-select">Run</label>
                <select
                  id="run-select"
                  className="field mt-1"
                  value={runId ?? ""}
                  onChange={(e) => update("run", e.target.value)}
                >
                  {runs.data.map((option) => (
                    <option key={option.run_id} value={option.run_id}>{option.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label" htmlFor="compare-select">Compare against</label>
                <select
                  id="compare-select"
                  className="field mt-1"
                  value={compareId ?? ""}
                  onChange={(e) => update("compare", e.target.value || null)}
                >
                  <option value="">No comparison</option>
                  {runs.data
                    .filter((option) => option.run_id !== runId)
                    .map((option) => (
                      <option key={option.run_id} value={option.run_id}>{option.label}</option>
                    ))}
                </select>
              </div>
            </div>
          </Card>
        )
      ) : null}

      {run.isLoading ? <LoadingState label="Loading run" /> : null}
      {run.error ? <ErrorState error={run.error} /> : null}

      {run.data ? (
        <>
          <Card title={run.data.label} subtitle={run.data.experiment}>
            <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <div><dt className="label">Folds</dt><dd className="tabular">{run.data.fold_count}</dd></div>
              <div><dt className="label">Samples</dt><dd className="tabular">{formatCount(run.data.sample_size)}</dd></div>
              <div><dt className="label">Positive rate</dt><dd className="tabular">{run.data.positive_rate.toFixed(4)}</dd></div>
              <div><dt className="label">Snapshot</dt><dd className="font-mono text-2xs">{shortHash(run.data.snapshot_hash)}</dd></div>
              <div><dt className="label">First cutoff</dt><dd className="text-2xs">{formatUtc(run.data.first_cutoff)}</dd></div>
              <div><dt className="label">Last cutoff</dt><dd className="text-2xs">{formatUtc(run.data.last_cutoff)}</dd></div>
              <div><dt className="label">Excluded folds</dt><dd className="tabular">{run.data.excluded_folds}</dd></div>
            </dl>

            {run.data.excluded_folds > 0 ? (
              <Callout tone="uncertainty" title={`${run.data.excluded_folds} folds excluded`}>
                These folds are right-censored: their horizon plus the reporting delay extends past
                the end of the evidence window, so their outcomes are not yet knowable. Scoring
                them would count “not reported yet” as “did not happen”, which inflates every
                precision figure on this page.
              </Callout>
            ) : null}
          </Card>

          <Card title="Metrics" subtitle={comparison.data ? `Compared against ${comparison.data.label}` : undefined}>
            <MetricGrid
              metrics={run.data.metrics}
              comparison={comparison.data?.metrics}
              comparisonLabel={comparison.data?.label}
            />
          </Card>

          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <ErrorBoundary label="The reliability diagram">
                <ReliabilityDiagram bins={run.data.reliability} />
              </ErrorBoundary>
            </Card>
            <Card>
              <ErrorBoundary label="The precision-recall curve">
                <PRCurve points={run.data.pr_curve} positiveRate={run.data.positive_rate} />
              </ErrorBoundary>
            </Card>
            <Card>
              <ErrorBoundary label="The budget-recall curve">
                <BudgetRecallCurve points={run.data.budget_recall} />
              </ErrorBoundary>
            </Card>
            <Card>
              <ErrorBoundary label="The abstention-risk curve">
                <AbstentionRiskCurve points={run.data.abstention_risk} />
              </ErrorBoundary>
            </Card>
          </div>

          <Card title="Arms" subtitle="Alternative configurations on identical folds">
            <ArmComparison arms={run.data.arms} />
          </Card>
        </>
      ) : null}
    </div>
  );
}
