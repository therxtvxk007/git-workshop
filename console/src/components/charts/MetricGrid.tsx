import { formatMetric } from "@/lib/format";
import type { Metric } from "@/lib/api/types";

/**
 * Metrics with their direction, interval and meaning attached.
 *
 * `lower_is_better` is carried in the data rather than inferred from the name,
 * so a comparison view cannot colour a Brier improvement as a regression. A
 * metric the run did not compute renders as "not computed" — never as 0, which
 * would be a good Brier score and a terrible lie.
 */
export function MetricGrid({
  metrics,
  comparison,
  comparisonLabel,
}: {
  metrics: Metric[];
  comparison?: Metric[];
  comparisonLabel?: string;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {metrics.map((metric) => {
        const other = comparison?.find((m) => m.key === metric.key);
        const delta =
          metric.value !== null && other?.value !== undefined && other.value !== null
            ? metric.value - other.value
            : null;
        const better =
          delta === null ? null : metric.lower_is_better ? delta < 0 : delta > 0;

        return (
          <div key={metric.key} className="card p-3">
            <p className="label">{metric.label}</p>
            <p className="tabular mt-1 text-xl font-semibold">
              {formatMetric(metric.value, metric.unit)}
            </p>
            {metric.ci ? (
              <p className="tabular text-2xs muted">
                95% CI {metric.ci[0].toFixed(4)} – {metric.ci[1].toFixed(4)}
              </p>
            ) : metric.value !== null ? (
              <p className="text-2xs muted">no interval reported</p>
            ) : null}

            {delta !== null ? (
              <p
                className={`tabular mt-1 text-2xs font-semibold ${
                  better ? "text-navy-600 dark:text-navy-300" : "text-uncertainty-700 dark:text-uncertainty-300"
                }`}
              >
                {delta >= 0 ? "+" : "−"}
                {Math.abs(delta).toFixed(4)} vs {comparisonLabel ?? "comparison"}{" "}
                {better ? "(better)" : "(worse)"}
              </p>
            ) : null}

            <p className="mt-1 text-2xs muted">{metric.description}</p>
            <p className="mt-1 text-2xs muted">
              {metric.lower_is_better ? "Lower is better." : "Higher is better."}
            </p>
          </div>
        );
      })}
    </div>
  );
}

export function ArmComparison({
  arms,
}: {
  arms: { arm_id: string; label: string; description: string; metrics: Metric[] }[];
}) {
  const keys = [...new Set(arms.flatMap((arm) => arm.metrics.map((m) => m.key)))];

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse">
        <caption className="sr-only">Metric comparison across evaluation arms</caption>
        <thead className="bg-[rgb(var(--surface-sunken))]">
          <tr>
            <th className="th">Arm</th>
            {keys.map((key) => (
              <th key={key} className="th">
                {arms.flatMap((a) => a.metrics).find((m) => m.key === key)?.label ?? key}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {arms.map((arm) => (
            <tr key={arm.arm_id}>
              <td className="td">
                <span className="font-medium">{arm.label}</span>
                <span className="block text-2xs muted">{arm.description}</span>
              </td>
              {keys.map((key) => {
                const metric = arm.metrics.find((m) => m.key === key);
                return (
                  <td key={key} className="td tabular">
                    {metric ? formatMetric(metric.value, metric.unit) : "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-2xs muted">
        Arms are alternative configurations scored on the same folds. The first row is the
        base-rate floor: an arm that does not beat it has not learned anything, whatever its other
        numbers look like.
      </p>
    </div>
  );
}
