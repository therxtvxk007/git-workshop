import { formatUtc, nowUtc } from "./format";

/**
 * Export with the caveats attached.
 *
 * The failure mode this file exists to prevent: a CSV leaves the console, loses
 * every piece of context, and is read three weeks later as a list of districts
 * at risk. So every export carries a header block naming the cutoff, the
 * snapshot hash, the data mode and the research-use restriction — in the file
 * itself, above the data, where a spreadsheet cannot hide it.
 */

export interface ExportContext {
  /** e.g. "ranked-districts". Becomes part of the filename. */
  name: string;
  cutoffAt: string;
  snapshotHash: string;
  dataMode: "live" | "synthetic";
  /** True when the rows describe a scenario rather than a forecast. */
  hypothetical?: boolean;
  /** Filters in force, recorded so the row set is reproducible. */
  filters?: Record<string, unknown>;
}

const RESEARCH_USE =
  "RESEARCH USE ONLY. Not operational intelligence. Probabilities are not calibrated " +
  "(calibration=identity@uncalibrated) and statuses come from a placeholder threshold " +
  "policy with no miss-rate guarantee. Do not use to direct response or resource allocation.";

const SYNTHETIC_WARNING =
  "SYNTHETIC DATA. Every row is generated demo data (is_demo=true). No value describes " +
  "any real district, event or outcome.";

const HYPOTHETICAL_WARNING =
  "HYPOTHETICAL. These rows are a scenario, not a forecast. They were produced by an " +
  "analyst-supplied override and were never emitted by the Pramaan-X engine.";

function headerLines(context: ExportContext): string[] {
  const lines = [
    `Pramaan-X Analyst Console export: ${context.name}`,
    `Exported at: ${formatUtc(nowUtc(), { seconds: true })}`,
    `Cutoff: ${formatUtc(context.cutoffAt)}`,
    `Snapshot: ${context.snapshotHash}`,
    `Data mode: ${context.dataMode.toUpperCase()}`,
    RESEARCH_USE,
  ];
  if (context.dataMode === "synthetic") lines.push(SYNTHETIC_WARNING);
  if (context.hypothetical) lines.push(HYPOTHETICAL_WARNING);
  if (context.filters && Object.keys(context.filters).length > 0) {
    lines.push(`Filters: ${JSON.stringify(context.filters)}`);
  }
  return lines;
}

/**
 * Quote a CSV cell.
 *
 * The leading apostrophe on `=`, `+`, `-` and `@` is deliberate: without it a
 * cell beginning with `=` is executed as a formula when the file is opened. An
 * export that runs code on the analyst's machine is not an acceptable way to
 * share a district table.
 */
function csvCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  let text = typeof value === "object" ? JSON.stringify(value) : String(value);
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  if (/[",\n\r]/.test(text)) text = `"${text.replace(/"/g, '""')}"`;
  return text;
}

export function toCsv<T extends Record<string, unknown>>(
  rows: T[],
  columns: { key: keyof T & string; header: string }[],
  context: ExportContext,
): string {
  const preamble = headerLines(context).map((line) => `# ${line}`);
  const head = columns.map((c) => csvCell(c.header)).join(",");
  const body = rows.map((row) => columns.map((c) => csvCell(row[c.key])).join(","));
  return [...preamble, "", head, ...body, ""].join("\n");
}

export function toJson<T>(rows: T[], context: ExportContext): string {
  return JSON.stringify(
    {
      export: {
        name: context.name,
        exported_at: nowUtc().toISOString(),
        cutoff_at: context.cutoffAt,
        snapshot_hash: context.snapshotHash,
        data_mode: context.dataMode,
        is_demo: context.dataMode === "synthetic",
        is_hypothetical: context.hypothetical === true,
        filters: context.filters ?? {},
        notice: [
          RESEARCH_USE,
          ...(context.dataMode === "synthetic" ? [SYNTHETIC_WARNING] : []),
          ...(context.hypothetical ? [HYPOTHETICAL_WARNING] : []),
        ],
      },
      row_count: Array.isArray(rows) ? rows.length : 0,
      rows,
    },
    null,
    2,
  );
}

export function exportFilename(context: ExportContext, extension: "csv" | "json"): string {
  const stamp = context.cutoffAt.slice(0, 10);
  const prefix = context.dataMode === "synthetic" ? "DEMO-" : "";
  const scenario = context.hypothetical ? "HYPOTHETICAL-" : "";
  return `${prefix}${scenario}pramaanx-${context.name}-${stamp}.${extension}`;
}

/** Triggers the browser download. Split out so the serialisers stay testable. */
export function downloadText(filename: string, contents: string, mime: string): void {
  const blob = new Blob([contents], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
