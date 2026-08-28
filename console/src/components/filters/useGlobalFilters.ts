import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import type { EventFamily, ForecastQuery, ForecastStatus } from "@/lib/api/types";

/**
 * Filters live in the URL, not in component state.
 *
 * The reason is collaborative rather than technical: analysts send each other
 * links. A filter set held in React state produces a link that opens on
 * somebody else's screen showing a different row set under the same headline,
 * which is how two people end up disagreeing about what the model said.
 */

export interface GlobalFilters {
  family: EventFamily | null;
  states: string[];
  statuses: ForecastStatus[];
  minProbability: number | null;
  search: string;
}

const STATUS_VALUES: ForecastStatus[] = ["alert", "watch", "monitor", "abstain", "insufficient_evidence"];

export function useGlobalFilters() {
  const [params, setParams] = useSearchParams();

  const filters = useMemo<GlobalFilters>(() => {
    const min = params.get("min");
    const parsedMin = min === null ? null : Number(min);
    return {
      family: (params.get("family") as EventFamily | null) ?? null,
      states: params.getAll("state"),
      statuses: params
        .getAll("status")
        .filter((s): s is ForecastStatus => STATUS_VALUES.includes(s as ForecastStatus)),
      // An unparseable ?min= is dropped rather than coerced to 0: a filter the
      // user cannot see in the UI but which is silently excluding rows is worse
      // than no filter.
      minProbability:
        parsedMin === null || Number.isNaN(parsedMin) || parsedMin < 0 || parsedMin > 1 ? null : parsedMin,
      search: params.get("q") ?? "",
    };
  }, [params]);

  const setFilters = useCallback(
    (next: Partial<GlobalFilters>) => {
      const merged = { ...filters, ...next };
      const updated = new URLSearchParams(params);
      updated.delete("family");
      updated.delete("state");
      updated.delete("status");
      updated.delete("min");
      updated.delete("q");
      if (merged.family) updated.set("family", merged.family);
      for (const state of merged.states) updated.append("state", state);
      for (const status of merged.statuses) updated.append("status", status);
      if (merged.minProbability !== null) updated.set("min", String(merged.minProbability));
      if (merged.search.trim()) updated.set("q", merged.search.trim());
      setParams(updated, { replace: true });
    },
    [filters, params, setParams],
  );

  const query = useMemo<ForecastQuery>(
    () => ({
      ...(filters.family ? { event_family: filters.family } : {}),
      ...(filters.states.length ? { states: filters.states } : {}),
      ...(filters.statuses.length ? { statuses: filters.statuses } : {}),
      ...(filters.minProbability !== null ? { min_probability: filters.minProbability } : {}),
      ...(filters.search.trim() ? { search: filters.search.trim() } : {}),
    }),
    [filters],
  );

  const active =
    !!filters.family ||
    filters.states.length > 0 ||
    filters.statuses.length > 0 ||
    filters.minProbability !== null ||
    filters.search.trim().length > 0;

  return { filters, setFilters, query, active };
}
