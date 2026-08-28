import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Card, Callout } from "@/components/ui/primitives";
import { EmptyState, LoadingState } from "@/components/states/StateViews";
import { EVENT_FAMILY_LABELS, formatProbability, formatUtc } from "@/lib/format";
import { useForecasts, useSnapshot } from "@/lib/queries";
import { cloud, type ScenarioSessionRecord } from "@/lib/cloud";

export function Scenarios() {
  const navigate = useNavigate();
  const { data: snapshot } = useSnapshot();
  const forecasts = useForecasts({});
  const [sessions, setSessions] = useState<ScenarioSessionRecord[] | null>(null);
  const [forecastId, setForecastId] = useState("");
  const [name, setName] = useState("");

  useEffect(() => {
    void cloud.listScenarioSessions().then(setSessions);
  }, []);

  const create = async () => {
    const forecast = forecasts.data?.find((f) => f.forecast_id === forecastId);
    if (!forecast || !snapshot) return;
    const record = await cloud.saveScenarioSession({
      name: name.trim() || `${forecast.district_name} what-if`,
      forecastId: forecast.forecast_id,
      districtName: forecast.district_name,
      eventFamily: forecast.event_family,
      baselineProbability: forecast.calibrated_probability,
      cutoffAt: snapshot.cutoff_at,
      snapshotHash: snapshot.snapshot_hash,
      isHypothetical: true,
      overrides: [],
    });
    navigate(`/scenarios/${record.id}`);
  };

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-lg font-semibold">Scenarios</h1>
        <p className="mt-1 max-w-prose text-sm muted">
          Hypothetical what-ifs, kept in a namespace of their own.
        </p>
      </header>

      <Callout tone="uncertainty" title="Scenarios are not forecasts">
        A scenario answers “what would the score look like if this input were different”. It is
        stored in separate tables with an <code>is_hypothetical</code> column the database will not
        let you set to false, it never appears in a forecast listing, it cannot produce an alert,
        and every export of one is watermarked. The isolation is structural because a filter is one
        forgotten WHERE clause from failing.
      </Callout>

      <Card title="New scenario">
        <div className="grid gap-3 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto] md:items-end">
          <div>
            <label className="label" htmlFor="scenario-forecast">Baseline forecast</label>
            <select
              id="scenario-forecast"
              className="field mt-1"
              value={forecastId}
              onChange={(e) => setForecastId(e.target.value)}
            >
              <option value="">Select a district-family forecast…</option>
              {(forecasts.data ?? []).slice(0, 120).map((forecast) => (
                <option key={forecast.forecast_id} value={forecast.forecast_id}>
                  {forecast.district_name} · {EVENT_FAMILY_LABELS[forecast.event_family]} ·{" "}
                  {formatProbability(forecast.calibrated_probability)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="scenario-name">Name</label>
            <input
              id="scenario-name"
              className="field mt-1"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Optional"
            />
          </div>
          <button type="button" className="btn-primary" disabled={!forecastId} onClick={() => void create()}>
            Create
          </button>
        </div>
      </Card>

      {sessions === null ? (
        <LoadingState label="Loading scenarios" />
      ) : sessions.length === 0 ? (
        <EmptyState title="No scenarios yet">
          Create one above. Scenarios are private to you unless an administrator says otherwise.
        </EmptyState>
      ) : (
        <Card title="Your scenarios">
          <ul className="divide-y divide-[rgb(var(--border))]">
            {sessions.map((session) => (
              <li key={session.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <div>
                  <Link className="text-sm font-medium underline" to={`/scenarios/${session.id}`}>
                    {session.name}
                  </Link>
                  <p className="text-2xs muted">
                    {session.districtName} · baseline {formatProbability(session.baselineProbability)} ·
                    cutoff {formatUtc(session.cutoffAt)} · {session.overrides.length} override
                    {session.overrides.length === 1 ? "" : "s"}
                  </p>
                </div>
                <span className="chip border-uncertainty-400/50">hypothetical</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
