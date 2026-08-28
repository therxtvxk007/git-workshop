import { Card, Callout } from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/states/StateViews";
import { formatCount, formatHours, formatProbability, formatUtc } from "@/lib/format";
import { useDataHealth } from "@/lib/queries";
import type { SourceHealth } from "@/lib/api/types";

const STATUS_CLASS: Record<SourceHealth["status"], string> = {
  healthy: "border-navy-500/40 bg-navy-500/10",
  degraded: "border-uncertainty-400/50 bg-uncertainty-400/15",
  outage: "border-alert-500/40 bg-alert-500/10",
};

/**
 * Coverage, delay and outages.
 *
 * This page exists to answer one question that the overview cannot: is a low
 * probability in this district a finding, or a gap? A district nobody reports
 * on produces no evidence, no candidates and therefore no risk — and looks
 * identical to a district that is genuinely quiet.
 */
export function DataHealthRoute() {
  const health = useDataHealth();

  if (health.isLoading) return <LoadingState label="Loading data health" />;
  if (health.error) return <ErrorState error={health.error} />;
  if (!health.data) return null;

  const outages = health.data.sources.filter((s) => s.status !== "healthy");
  const underCovered = health.data.districts.filter((d) => d.under_covered);

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-lg font-semibold">Data health</h1>
        <p className="mt-1 max-w-prose text-sm muted">
          Source coverage, ingestion delay and outages as at {formatUtc(health.data.generated_at)}.
          Read this before concluding that a quiet district is a safe one.
        </p>
      </header>

      {outages.length > 0 ? (
        <Callout tone="uncertainty" title={`${outages.length} source(s) are not healthy`}>
          Forecasts computed during an outage saw less evidence than usual. Their probabilities are
          not wrong, but they are less informed, and a fall in a district's score during an outage
          is a fact about the pipeline rather than about the district.
        </Callout>
      ) : null}

      <div className="grid gap-3 md:grid-cols-2">
        {health.data.sources.map((source) => (
          <div key={source.source_id} className={`card border p-4 ${STATUS_CLASS[source.status]}`}>
            <div className="flex items-start justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold">{source.name}</h2>
                <p className="text-2xs uppercase tracking-wide muted">{source.status}</p>
              </div>
              <p className="tabular text-right text-lg font-semibold">
                {formatProbability(source.coverage)}
                <span className="block text-2xs font-normal muted">coverage</span>
              </p>
            </div>

            <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
              <div><dt className="label">Districts</dt><dd className="tabular">{source.districts_covered}</dd></div>
              <div><dt className="label">Median delay</dt><dd className="tabular">{formatHours(source.median_delay_hours)}</dd></div>
              <div><dt className="label">P90 delay</dt><dd className="tabular">{formatHours(source.p90_delay_hours)}</dd></div>
              <div><dt className="label">Last document</dt><dd className="text-2xs">{formatUtc(source.last_document_at)}</dd></div>
            </dl>

            {source.outages.length > 0 ? (
              <ul className="mt-3 space-y-1 border-t border-[rgb(var(--border))] pt-2 text-2xs">
                {source.outages.map((outage) => (
                  <li key={outage.from}>
                    <span className="font-semibold">
                      {formatUtc(outage.from)} → {outage.to ? formatUtc(outage.to) : "ongoing"}
                    </span>
                    <span className="block muted">{outage.reason}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ))}
      </div>

      <Card
        title="District coverage"
        subtitle={`${underCovered.length} of ${health.data.districts.length} districts are under-covered`}
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse">
            <caption className="sr-only">Document coverage by district over the trailing 30 days</caption>
            <thead className="bg-[rgb(var(--surface-sunken))]">
              <tr>
                <th className="th">District</th>
                <th className="th">State</th>
                <th className="th">Documents (30 d)</th>
                <th className="th">Coverage</th>
              </tr>
            </thead>
            <tbody>
              {[...health.data.districts]
                .sort((a, b) => a.coverage - b.coverage)
                .map((district) => (
                  <tr
                    key={district.district_id}
                    className={district.under_covered ? "bg-uncertainty-400/10" : ""}
                  >
                    <td className="td font-medium">
                      {district.district_name}
                      {district.under_covered ? (
                        <span className="ml-2 chip border-uncertainty-400/50">under-covered</span>
                      ) : null}
                    </td>
                    <td className="td">{district.state}</td>
                    <td className="td tabular">{formatCount(district.documents_30d)}</td>
                    <td className="td tabular">{formatProbability(district.coverage)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-2xs muted">
          Sorted worst-first, because the districts at the bottom of the overview ranking and the
          top of this table are frequently the same districts.
        </p>
      </Card>
    </div>
  );
}
