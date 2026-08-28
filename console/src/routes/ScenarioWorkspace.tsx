import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Card, Callout, ProbabilityBar, StatusBadge } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/states/StateViews";
import {
  EVENT_FAMILY_LABELS,
  formatProbability,
  formatProbabilityDelta,
  formatUtc,
} from "@/lib/format";
import { apiClient } from "@/lib/api/client";
import { useContributions, useSnapshot } from "@/lib/queries";
import { downloadText, exportFilename, toJson } from "@/lib/export";
import { auditExport } from "@/lib/audit.functions";
import { cloud, type ScenarioSessionRecord } from "@/lib/cloud";
import type { ScenarioResult } from "@/lib/api/types";

/**
 * Baseline versus hypothetical, side by side.
 *
 * The hypothetical column never renders a status badge as though it were live:
 * the field is called `hypothetical_status_if_real` and is labelled "would be",
 * because a scenario that displays an ALERT badge is one screenshot away from
 * being circulated as an alert.
 */
export function ScenarioWorkspace() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { data: snapshot } = useSnapshot();
  const [session, setSession] = useState<ScenarioSessionRecord | null | undefined>(undefined);
  const [values, setValues] = useState<Record<string, number>>({});
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!sessionId) return;
    void cloud.getScenarioSession(sessionId).then(setSession);
  }, [sessionId]);

  const contributions = useContributions(session?.forecastId);

  // Overrides are offered over the contribution groups' own members, so an
  // analyst can only move levers the model actually has.
  const levers = useMemo(
    () => (contributions.data?.groups ?? []).flatMap((group) => group.members).slice(0, 6),
    [contributions.data],
  );

  useEffect(() => {
    if (levers.length === 0) return;
    setValues((current) =>
      Object.keys(current).length > 0
        ? current
        : Object.fromEntries(
            levers.map((lever) => [lever.feature, typeof lever.value === "number" ? lever.value : 0]),
          ),
    );
  }, [levers]);

  if (session === undefined) return <LoadingState label="Loading scenario" />;
  if (session === null) return <EmptyState title="No such scenario" />;

  const overrides = levers
    .map((lever) => ({
      feature: lever.feature,
      label: lever.label,
      baseline_value: typeof lever.value === "number" ? lever.value : 0,
      hypothetical_value: values[lever.feature] ?? (typeof lever.value === "number" ? lever.value : 0),
    }))
    .filter((override) => override.baseline_value !== override.hypothetical_value);

  const evaluate = async () => {
    setError(null);
    try {
      setResult(
        await apiClient.evaluateScenario({ forecast_id: session.forecastId, overrides }),
      );
    } catch (caught) {
      setError(caught);
    }
  };

  const exportScenario = async () => {
    if (!result) return;
    const context = {
      name: "scenario",
      cutoffAt: session.cutoffAt,
      snapshotHash: session.snapshotHash,
      dataMode: snapshot?.data_mode ?? "synthetic",
      hypothetical: true,
      filters: { forecast_id: session.forecastId },
    } as const;
    downloadText(exportFilename(context, "json"), toJson([result], context), "application/json");
    await auditExport("scenario", "json", 1, {
      cutoffAt: session.cutoffAt,
      snapshotHash: session.snapshotHash,
      dataMode: context.dataMode,
      isHypothetical: true,
    });
  };

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <nav className="text-2xs muted">
            <Link className="underline" to="/scenarios">Scenarios</Link>
          </nav>
          <h1 className="mt-1 text-lg font-semibold">{session.name}</h1>
          <p className="mt-1 text-sm muted">
            {session.districtName} ·{" "}
            {EVENT_FAMILY_LABELS[session.eventFamily as keyof typeof EVENT_FAMILY_LABELS] ??
              session.eventFamily}{" "}
            · cutoff {formatUtc(session.cutoffAt)}
          </p>
        </div>
        <span className="chip border-uncertainty-400/60 bg-uncertainty-400/20 font-semibold uppercase">
          Hypothetical
        </span>
      </header>

      <Callout tone="uncertainty" title="Nothing on this page is a forecast">
        These numbers were produced by moving inputs by hand. They are not engine output, they are
        not written to the forecast namespace, and the JSON export is watermarked
        <code className="mx-1">HYPOTHETICAL</code> in its filename and its header block.
      </Callout>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card title="Overrides" subtitle="Levers the model actually has">
          {contributions.isLoading ? <LoadingState label="Loading levers" /> : null}
          {contributions.error ? <ErrorState error={contributions.error} /> : null}

          <div className="space-y-4">
            {levers.map((lever) => {
              const baseline = typeof lever.value === "number" ? lever.value : 0;
              const current = values[lever.feature] ?? baseline;
              return (
                <div key={lever.feature}>
                  <label className="label" htmlFor={`lever-${lever.feature}`}>
                    {lever.label}{" "}
                    <span className="tabular normal-case">
                      {current.toFixed(2)}{" "}
                      <span className="muted">(baseline {baseline.toFixed(2)})</span>
                    </span>
                  </label>
                  <input
                    id={`lever-${lever.feature}`}
                    type="range"
                    min={0}
                    max={20}
                    step={0.5}
                    className="mt-2 w-full"
                    value={current}
                    onChange={(e) =>
                      setValues((v) => ({ ...v, [lever.feature]: Number(e.target.value) }))
                    }
                  />
                  <p className="text-2xs muted">{lever.description}</p>
                </div>
              );
            })}
          </div>

          <button
            type="button"
            className="btn-primary mt-4 w-full"
            disabled={overrides.length === 0}
            onClick={() => void evaluate()}
          >
            {overrides.length === 0 ? "Move a lever to evaluate" : `Evaluate ${overrides.length} override(s)`}
          </button>
        </Card>

        <Card title="Baseline vs hypothetical">
          {error ? <ErrorState error={error} /> : null}
          {!result ? (
            <p className="text-sm muted">
              Adjust an override and evaluate. Until then, only the baseline is shown — a scenario
              workspace that displays a hypothetical by default is a scenario workspace people
              screenshot by accident.
            </p>
          ) : (
            <div className="space-y-4">
              <div>
                <p className="label">Baseline (engine)</p>
                <ProbabilityBar
                  value={result.baseline_probability}
                  interval={result.baseline_interval}
                />
                <p className="mt-1 text-2xs muted">
                  Status <StatusBadge status={result.baseline_status} />
                </p>
              </div>

              <div className="rounded border border-uncertainty-400/50 bg-uncertainty-400/10 p-3">
                <p className="label">Hypothetical (not a forecast)</p>
                <ProbabilityBar
                  value={result.hypothetical_probability}
                  interval={result.hypothetical_interval}
                />
                <p className="tabular mt-1 text-sm font-semibold">
                  {formatProbabilityDelta(
                    result.hypothetical_probability - result.baseline_probability,
                  )}{" "}
                  <span className="font-normal muted">
                    from {formatProbability(result.baseline_probability)}
                  </span>
                </p>
                <p className="mt-1 text-2xs muted">
                  Would be classified <strong>{result.hypothetical_status_if_real}</strong> if it
                  were a real forecast. It is not one, so no status is assigned.
                </p>
              </div>

              <p className="text-2xs muted">{result.caveat}</p>

              <button type="button" className="btn w-full" onClick={() => void exportScenario()}>
                Export watermarked JSON
              </button>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
