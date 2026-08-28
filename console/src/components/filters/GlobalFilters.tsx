import { EVENT_FAMILY_LABELS, STATUS_LABELS, formatProbability } from "@/lib/format";
import type { EventFamily, ForecastStatus } from "@/lib/api/types";
import type { GlobalFilters as Filters } from "./useGlobalFilters";

const FAMILIES = Object.keys(EVENT_FAMILY_LABELS) as EventFamily[];
const STATUSES: ForecastStatus[] = ["alert", "watch", "monitor", "abstain", "insufficient_evidence"];

export function GlobalFilters({
  filters,
  states,
  onChange,
  resultCount,
  totalCount,
}: {
  filters: Filters;
  states: string[];
  onChange: (next: Partial<Filters>) => void;
  resultCount: number;
  totalCount: number;
}) {
  const toggle = <T,>(list: T[], value: T): T[] =>
    list.includes(value) ? list.filter((v) => v !== value) : [...list, value];

  return (
    <div className="card p-4 no-print">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div>
          <label className="label" htmlFor="filter-family">Event family</label>
          <select
            id="filter-family"
            className="field mt-1"
            value={filters.family ?? ""}
            onChange={(e) => onChange({ family: (e.target.value || null) as EventFamily | null })}
          >
            <option value="">All families</option>
            {FAMILIES.map((family) => (
              <option key={family} value={family}>{EVENT_FAMILY_LABELS[family]}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="label" htmlFor="filter-search">Search district</label>
          <input
            id="filter-search"
            type="search"
            className="field mt-1"
            placeholder="District or state"
            value={filters.search}
            onChange={(e) => onChange({ search: e.target.value })}
          />
        </div>

        <div>
          <label className="label" htmlFor="filter-min">
            Minimum probability{" "}
            <span className="tabular normal-case">
              {filters.minProbability === null ? "off" : formatProbability(filters.minProbability)}
            </span>
          </label>
          <input
            id="filter-min"
            type="range"
            min={0}
            max={0.95}
            step={0.05}
            className="mt-3 w-full"
            value={filters.minProbability ?? 0}
            onChange={(e) => {
              const value = Number(e.target.value);
              onChange({ minProbability: value === 0 ? null : value });
            }}
          />
        </div>

        <div>
          <span className="label">States</span>
          <select
            multiple
            aria-label="States"
            className="field mt-1 h-24"
            value={filters.states}
            onChange={(e) =>
              onChange({ states: [...e.target.selectedOptions].map((o) => o.value) })
            }
          >
            {states.map((state) => (
              <option key={state} value={state}>{state}</option>
            ))}
          </select>
        </div>
      </div>

      <fieldset className="mt-4">
        <legend className="label">Status</legend>
        <div className="mt-1 flex flex-wrap gap-2">
          {STATUSES.map((status) => {
            const checked = filters.statuses.includes(status);
            return (
              <label
                key={status}
                className={`chip cursor-pointer text-xs ${checked ? "border-navy-500 bg-navy-500/15" : ""}`}
              >
                <input
                  type="checkbox"
                  className="mr-1"
                  checked={checked}
                  onChange={() => onChange({ statuses: toggle(filters.statuses, status) })}
                />
                {STATUS_LABELS[status]}
              </label>
            );
          })}
        </div>
      </fieldset>

      <p className="mt-3 text-2xs muted" aria-live="polite">
        Showing <span className="tabular">{resultCount}</span> of{" "}
        <span className="tabular">{totalCount}</span> district-family forecasts at this cutoff.
        Filters are held in the URL, so this exact view can be shared as a link.
      </p>
    </div>
  );
}
