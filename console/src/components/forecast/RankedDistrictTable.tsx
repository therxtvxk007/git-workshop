import { useMemo, useState } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import { Link } from "react-router-dom";
import { ProbabilityBar, StatusBadge } from "@/components/ui/primitives";
import {
  EVENT_FAMILY_LABELS,
  formatCount,
  formatInterval,
  formatProbability,
} from "@/lib/format";
import { downloadText, exportFilename, toCsv, toJson, type ExportContext } from "@/lib/export";
import { auditExport } from "@/lib/audit.functions";
import type { ForecastSummary } from "@/lib/api/types";

const columnHelper = createColumnHelper<ForecastSummary>();

/**
 * The ranked table.
 *
 * Sorted by calibrated probability by default, but the columns that qualify
 * that number — the interval, the independent-cluster count, the status — are
 * beside it rather than hidden behind a detail click. A table that shows only
 * the rank invites reading the top row as "the most dangerous district", when
 * it may simply be the best-covered one.
 */
export function RankedDistrictTable({
  forecasts,
  exportContext,
}: {
  forecasts: ForecastSummary[];
  exportContext: Omit<ExportContext, "name">;
}) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "calibrated_probability", desc: true },
  ]);

  const columns = useMemo(
    () => [
      columnHelper.accessor("district_name", {
        header: "District",
        cell: (info) => (
          <Link
            to={`/forecasts/${info.row.original.forecast_id}`}
            className="font-medium underline decoration-dotted underline-offset-2"
          >
            {info.getValue()}
          </Link>
        ),
      }),
      columnHelper.accessor("state", { header: "State" }),
      columnHelper.accessor("event_family", {
        header: "Family",
        cell: (info) => EVENT_FAMILY_LABELS[info.getValue()],
      }),
      columnHelper.accessor("calibrated_probability", {
        header: "Probability",
        cell: (info) => (
          <ProbabilityBar
            value={info.getValue()}
            interval={info.row.original.interval}
            baseRate={info.row.original.base_rate}
            compact
          />
        ),
      }),
      columnHelper.accessor((row) => row.interval?.upper ?? null, {
        id: "interval",
        header: "Interval",
        cell: (info) => (
          <span className="tabular text-2xs muted">{formatInterval(info.row.original.interval)}</span>
        ),
      }),
      columnHelper.accessor("status", {
        header: "Status",
        cell: (info) => <StatusBadge status={info.getValue()} />,
      }),
      columnHelper.accessor("independent_cluster_count", {
        header: "Ind. clusters",
        cell: (info) => (
          <span className="tabular" title={`${info.row.original.evidence_count} evidence items before de-syndication`}>
            {info.getValue()}
            <span className="muted"> / {info.row.original.evidence_count}</span>
          </span>
        ),
      }),
      columnHelper.accessor("epistemic_uncertainty", {
        header: "Epistemic unc.",
        cell: (info) => <span className="tabular">{formatProbability(info.getValue())}</span>,
      }),
    ],
    [],
  );

  const table = useReactTable({
    data: forecasts,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const exportRows = () =>
    table.getSortedRowModel().rows.map((row) => ({
      district_id: row.original.district_id,
      district: row.original.district_name,
      state: row.original.state,
      event_family: row.original.event_family,
      calibrated_probability: row.original.calibrated_probability,
      raw_probability: row.original.raw_probability,
      interval_lower: row.original.interval?.lower ?? null,
      interval_upper: row.original.interval?.upper ?? null,
      interval_coverage: row.original.interval?.coverage ?? null,
      base_rate: row.original.base_rate,
      epistemic_uncertainty: row.original.epistemic_uncertainty,
      status: row.original.status,
      evidence_count: row.original.evidence_count,
      independent_cluster_count: row.original.independent_cluster_count,
      horizon_days: row.original.horizon_days,
      cutoff_at: row.original.cutoff_at,
      snapshot_hash: row.original.snapshot_hash,
      is_demo: row.original.is_demo,
    }));

  const runExport = async (format: "csv" | "json") => {
    const rows = exportRows();
    const context: ExportContext = { ...exportContext, name: "ranked-districts" };
    const contents =
      format === "csv"
        ? toCsv(
            rows,
            (Object.keys(rows[0] ?? {}) as (keyof (typeof rows)[number] & string)[]).map((key) => ({
              key,
              header: key,
            })),
            context,
          )
        : toJson(rows, context);
    downloadText(exportFilename(context, format), contents, format === "csv" ? "text/csv" : "application/json");
    try {
      await auditExport("ranked-districts", format, rows.length, {
        cutoffAt: context.cutoffAt,
        snapshotHash: context.snapshotHash,
        dataMode: context.dataMode,
        isHypothetical: false,
      });
    } catch {
      // A failed audit write must not silently discard the file the analyst
      // already has. It is surfaced as a console warning and the export stands.
      console.warn("Export completed but could not be recorded in the audit log.");
    }
  };

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 no-print">
        <p className="text-2xs muted">
          <span className="tabular">{forecasts.length}</span> rows. Exports carry the cutoff,
          the snapshot hash and the research-use notice in the file itself.
        </p>
        <div className="flex gap-2">
          <button type="button" className="btn px-2 py-1 text-xs" onClick={() => void runExport("csv")}>
            Export CSV
          </button>
          <button type="button" className="btn px-2 py-1 text-xs" onClick={() => void runExport("json")}>
            Export JSON
          </button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-[rgb(var(--border))]">
        <table className="w-full min-w-[860px] border-collapse">
          <caption className="sr-only">
            District forecasts ranked by calibrated probability, with intervals, status and
            evidence independence.
          </caption>
          <thead className="bg-[rgb(var(--surface-sunken))]">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => {
                  const sorted = header.column.getIsSorted();
                  return (
                    <th
                      key={header.id}
                      className="th"
                      aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}
                    >
                      <button
                        type="button"
                        className="flex items-center gap-1"
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        <span aria-hidden>{sorted === "asc" ? "▲" : sorted === "desc" ? "▼" : "↕"}</span>
                      </button>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="hover:bg-[rgb(var(--surface-sunken))]">
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="td">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-2 text-2xs muted">
        Ranking is by calibrated probability at this cutoff. A district can rank highly because it
        is genuinely at risk or because it is unusually well covered; the independent-cluster
        column and{" "}
        <Link className="underline" to="/data-health">data health</Link> are how you tell the
        difference. Total districts scored: {formatCount(forecasts.length)}.
      </p>
    </div>
  );
}
