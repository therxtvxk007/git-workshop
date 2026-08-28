import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Card, DefinitionList, StatusBadge, Tabs, Callout } from "@/components/ui/primitives";
import { ProbabilityCompare } from "@/components/forecast/ProbabilityCompare";
import { ContributionGroups } from "@/components/forecast/ContributionGroups";
import { ProvenancePanel } from "@/components/forecast/ProvenancePanel";
import { EvidenceCard } from "@/components/evidence/EvidenceCard";
import { EvidenceDrawer } from "@/components/evidence/EvidenceDrawer";
import { HistoricalTrend } from "@/components/charts/EvaluationCharts";
import { ErrorState, LoadingState, EmptyState } from "@/components/states/StateViews";
import { ErrorBoundary } from "@/components/states/ErrorBoundary";
import {
  EVENT_FAMILY_LABELS,
  formatProbability,
  formatUtc,
  nowUtc,
} from "@/lib/format";
import { useContributions, useEvidence, useForecast, useForecastHistory } from "@/lib/queries";
import type { Stance } from "@/lib/api/types";

type TabId = "supports" | "contradicts" | "context" | "all";

export function ForecastDetailRoute() {
  const { forecastId } = useParams<{ forecastId: string }>();
  const forecast = useForecast(forecastId);
  const contributions = useContributions(forecastId);
  const [tab, setTab] = useState<TabId>("all");
  const [openEvidence, setOpenEvidence] = useState<string | null>(null);

  const history = useForecastHistory(
    forecast.data?.district_id,
    forecast.data?.event_family,
  );
  // The detail record carries evidence *references*; the full items come from
  // the evidence endpoint, which is also where permission is enforced.
  const evidence = useEvidence(
    forecast.data
      ? { district_id: forecast.data.district_id, event_family: forecast.data.event_family, include_post_cutoff: true }
      : {},
  );

  if (forecast.isLoading) return <LoadingState label="Loading forecast" />;
  if (forecast.error) return <ErrorState error={forecast.error} />;
  if (!forecast.data) return <EmptyState title="No such forecast" />;

  const detail = forecast.data;
  const items = evidence.data?.items ?? [];
  const filtered = tab === "all" ? items : items.filter((i) => i.stance === (tab as Stance));
  const counts = (stance: Stance) => items.filter((i) => i.stance === stance).length;
  const postCutoff = items.filter((i) => i.post_cutoff).length;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <nav className="text-2xs muted">
            <Link className="underline" to="/">Overview</Link> / {detail.state}
          </nav>
          <h1 className="mt-1 text-lg font-semibold">
            {detail.district_name}
            <span className="muted font-normal"> · {EVENT_FAMILY_LABELS[detail.event_family]}</span>
          </h1>
          <p className="mt-1 text-sm muted">
            {detail.horizon_days}-day horizon from cutoff {formatUtc(detail.cutoff_at)}. This is a
            statement about the {detail.horizon_days} days following the cutoff, not about today.
          </p>
        </div>
        <StatusBadge status={detail.status} size="lg" />
      </header>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <Card title="Probability" subtitle="Raw, calibrated, and against the base rate">
          <ProbabilityCompare forecast={detail} />
        </Card>

        <Card title="Trend" subtitle="This district and family at earlier cutoffs">
          <ErrorBoundary label="The trend chart">
            {history.isLoading ? (
              <LoadingState label="Loading history" />
            ) : history.error ? (
              <ErrorState error={history.error} />
            ) : (
              <HistoricalTrend points={history.data ?? []} now={nowUtc()} />
            )}
          </ErrorBoundary>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <Card
          title="Evidence"
          subtitle={`${items.length} items, ${detail.independent_cluster_count} independent clusters`}
        >
          {evidence.error ? (
            <ErrorState error={evidence.error} />
          ) : (
            <>
              {evidence.data && evidence.data.withheld > 0 ? (
                <Callout tone="uncertainty" title={`${evidence.data.withheld} item(s) withheld`}>
                  Some evidence behind this forecast is not redistributable under its source
                  licence. It is counted here so the evidence base is not understated.
                </Callout>
              ) : null}

              {postCutoff > 0 ? (
                <Callout tone="uncertainty" title={`${postCutoff} item(s) arrived after the cutoff`}>
                  Shown and labelled. The model did not use them; they are here so you can see what
                  it was missing, never as support for the score.
                </Callout>
              ) : null}

              <div className="mt-3">
                <Tabs<TabId>
                  active={tab}
                  onChange={setTab}
                  tabs={[
                    { id: "all", label: "All", count: items.length },
                    { id: "supports", label: "Supports", count: counts("supports") },
                    { id: "contradicts", label: "Contradicts", count: counts("contradicts") },
                    { id: "context", label: "Context", count: counts("context") },
                  ]}
                />
              </div>

              <div className="mt-3 space-y-2">
                {evidence.isLoading ? <LoadingState label="Loading evidence" /> : null}
                {!evidence.isLoading && filtered.length === 0 ? (
                  <EmptyState title="No evidence in this category">
                    {detail.status === "insufficient_evidence"
                      ? "This forecast carries the insufficient-evidence status precisely because the evidence needed to assess it is not available."
                      : "No items matched this stance."}
                  </EmptyState>
                ) : null}
                {filtered.map((item) => (
                  <EvidenceCard
                    key={item.evidence_id}
                    item={item}
                    cutoffAt={detail.cutoff_at}
                    onOpen={(opened) => setOpenEvidence(opened.evidence_id)}
                  />
                ))}
              </div>
            </>
          )}
        </Card>

        <div className="space-y-4">
          <Card title="Contribution" subtitle="Grouped feature attribution">
            <ErrorBoundary label="The contribution panel">
              {contributions.isLoading ? (
                <LoadingState label="Loading contributions" />
              ) : contributions.error ? (
                <ErrorState error={contributions.error} />
              ) : contributions.data ? (
                <ContributionGroups report={contributions.data} />
              ) : null}
            </ErrorBoundary>
          </Card>

          <Card title="Hypothesis" subtitle="What was actually proposed">
            <DefinitionList
              items={[
                { label: "Event id", value: <code className="text-2xs">{detail.hypothesis.event_id}</code> },
                { label: "Event type", value: detail.hypothesis.event_type },
                { label: "Generated by", value: detail.hypothesis.generated_by.join(", ") },
                { label: "Novelty", value: formatProbability(detail.hypothesis.novelty_score) },
                {
                  label: "Time buckets",
                  value: Object.entries(detail.hypothesis.time_bucket_probabilities)
                    .map(([bucket, p]) => `${bucket}: ${formatProbability(p)}`)
                    .join(" · ") || "—",
                },
                {
                  label: "Severity",
                  value: Object.entries(detail.hypothesis.severity_distribution)
                    .map(([level, p]) => `${level}: ${formatProbability(p)}`)
                    .join(" · ") || "—",
                },
              ]}
            />
          </Card>

          <Card title="Provenance" subtitle="Everything needed to reproduce this number">
            <ProvenancePanel provenance={detail.provenance} />
          </Card>

          {detail.observed_outcome ? (
            <Card title="Observed outcome">
              {Date.parse(detail.observed_outcome.scoreable_from) > nowUtc().getTime() ? (
                <Callout tone="uncertainty" title="Not yet scoreable">
                  An outcome has been matched, but the horizon and reporting delay have not both
                  elapsed (scoreable from {formatUtc(detail.observed_outcome.scoreable_from)}). It is
                  withheld rather than shown, because a right-censored non-event displayed as a miss
                  makes the model look worse — or better — than it is.
                </Callout>
              ) : (
                <DefinitionList
                  items={[
                    { label: "Occurred", value: detail.observed_outcome.occurred ? "Yes" : "No" },
                    { label: "Resolved at", value: formatUtc(detail.observed_outcome.resolved_at) },
                    {
                      label: "Match confidence",
                      value: formatProbability(detail.observed_outcome.match_confidence),
                    },
                  ]}
                />
              )}
            </Card>
          ) : null}
        </div>
      </div>

      <EvidenceDrawer
        evidenceId={openEvidence}
        cutoffAt={detail.cutoff_at}
        onClose={() => setOpenEvidence(null)}
      />
    </div>
  );
}
