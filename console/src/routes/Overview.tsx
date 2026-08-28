import { useNavigate } from "react-router-dom";
import { GlobalFilters } from "@/components/filters/GlobalFilters";
import { useGlobalFilters } from "@/components/filters/useGlobalFilters";
import { SummaryCards } from "@/components/forecast/SummaryCards";
import { DistrictMap, MapLegendNote } from "@/components/forecast/DistrictMap";
import { RankedDistrictTable } from "@/components/forecast/RankedDistrictTable";
import { EmptyState, ErrorState, LoadingState } from "@/components/states/StateViews";
import { ErrorBoundary } from "@/components/states/ErrorBoundary";
import { Card } from "@/components/ui/primitives";
import { useDataHealth, useDistricts, useForecasts, useSnapshot } from "@/lib/queries";

export function Overview() {
  const navigate = useNavigate();
  const { filters, setFilters, query, active } = useGlobalFilters();
  const { data: snapshot } = useSnapshot();
  const districts = useDistricts();
  const forecasts = useForecasts(query);
  const unfiltered = useForecasts({});
  const dataHealth = useDataHealth();

  const states = [...new Set((districts.data ?? []).map((d) => d.state))].sort();
  const underCovered = dataHealth.data
    ? dataHealth.data.districts.filter((d) => d.under_covered).length
    : null;

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-lg font-semibold">Overview</h1>
        <p className="mt-1 max-w-prose text-sm muted">
          District-level forecasts for the active cutoff, ranked by calibrated probability.
          Every row is a claim about a 30-day horizon from the cutoff, not about today.
        </p>
      </header>

      <GlobalFilters
        filters={filters}
        states={states}
        onChange={setFilters}
        resultCount={forecasts.data?.length ?? 0}
        totalCount={unfiltered.data?.length ?? 0}
      />

      {forecasts.isLoading ? <LoadingState label="Loading forecasts" /> : null}
      {forecasts.error ? <ErrorState error={forecasts.error} /> : null}

      {forecasts.data ? (
        <>
          <SummaryCards forecasts={forecasts.data} underCovered={underCovered} />

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
            <Card title="District map" subtitle="Highest probability per district">
              <ErrorBoundary label="The map">
                <div className="h-[360px]">
                  <DistrictMap
                    districts={districts.data ?? []}
                    forecasts={forecasts.data}
                    onSelect={(forecast) => navigate(`/forecasts/${forecast.forecast_id}`)}
                  />
                </div>
              </ErrorBoundary>
              <div className="mt-2">
                <MapLegendNote family={filters.family} />
              </div>
            </Card>

            <Card title="Ranked districts" subtitle="Sortable, exportable, and the authoritative view">
              {forecasts.data.length === 0 ? (
                <EmptyState title={active ? "No districts match these filters" : "No forecasts at this cutoff"}>
                  {active
                    ? "The query succeeded and matched nothing. Widen the filters, or clear the minimum probability."
                    : "The engine returned no scored forecasts for this snapshot. That is a real answer about the run, not a display problem."}
                </EmptyState>
              ) : (
                <RankedDistrictTable
                  forecasts={forecasts.data}
                  exportContext={{
                    cutoffAt: snapshot?.cutoff_at ?? "",
                    snapshotHash: snapshot?.snapshot_hash ?? "",
                    dataMode: snapshot?.data_mode ?? "synthetic",
                    filters: query as Record<string, unknown>,
                  }}
                />
              )}
            </Card>
          </div>
        </>
      ) : null}
    </div>
  );
}
