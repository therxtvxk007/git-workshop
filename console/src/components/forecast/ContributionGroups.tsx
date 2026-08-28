import { Callout } from "@/components/ui/primitives";
import type { ContributionReport } from "@/lib/api/types";

/**
 * Grouped attribution, drawn as a signed bar per group.
 *
 * Groups rather than individual features, because a list of forty features
 * ranked by SHAP value reads as an explanation and is mostly noise. The caveat
 * is rendered above the chart, not tucked into a tooltip, since the most common
 * misreading — "the model says the strike caused this" — is exactly what the
 * caveat rules out.
 */
export function ContributionGroups({ report }: { report: ContributionReport }) {
  const max = Math.max(0.1, ...report.groups.map((g) => Math.abs(g.contribution)));

  return (
    <div className="space-y-3">
      <Callout tone="uncertainty" title="How to read this">
        {report.method_caveat}
      </Callout>

      <ul className="space-y-3">
        {report.groups.map((group) => {
          const width = (Math.abs(group.contribution) / max) * 50;
          const positive = group.contribution >= 0;
          return (
            <li key={group.group}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-medium">{group.label}</span>
                <span className="tabular text-2xs muted">
                  {group.contribution >= 0 ? "+" : "−"}
                  {Math.abs(group.contribution).toFixed(3)} log-odds
                </span>
              </div>
              <div className="relative mt-1 h-3 rounded bg-[rgb(var(--surface-sunken))]">
                <div className="absolute inset-y-0 left-1/2 w-px bg-[rgb(var(--border))]" />
                <div
                  className={`absolute inset-y-0 rounded ${positive ? "bg-navy-500" : "bg-uncertainty-500"}`}
                  style={
                    positive
                      ? { left: "50%", width: `${width}%` }
                      : { right: "50%", width: `${width}%` }
                  }
                />
              </div>
              <ul className="mt-1.5 space-y-0.5 pl-3 text-2xs muted">
                {group.members.map((member) => (
                  <li key={member.feature} className="flex justify-between gap-3">
                    <span title={member.description}>{member.label}</span>
                    <span className="tabular shrink-0">
                      {member.contribution >= 0 ? "+" : "−"}
                      {Math.abs(member.contribution).toFixed(3)}
                      <span className="ml-2 opacity-70">
                        {typeof member.value === "number" ? member.value.toFixed(2) : (member.value ?? "—")}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </li>
          );
        })}
      </ul>

      <p className="text-2xs muted">
        Baseline: <span className="tabular">{report.baseline_log_odds.toFixed(3)}</span> log-odds.
        Method: <code>{report.method}</code>.
      </p>
    </div>
  );
}
