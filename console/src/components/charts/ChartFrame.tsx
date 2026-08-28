import { useId, useState, type ReactNode } from "react";

/**
 * Every chart in this console ships with its numbers.
 *
 * `ChartDataTable` is not a courtesy for screen-reader users; it is the primary
 * record. A reliability diagram read off a 300-pixel SVG cannot tell you that
 * the top bin holds nine samples, and "the curve looks fine" is not a
 * calibration claim. So the toggle is always present, the table is real markup,
 * and the SVG is `aria-hidden` with a described-by summary.
 */
export function ChartFrame({
  title,
  description,
  columns,
  rows,
  children,
  footnote,
}: {
  title: string;
  description: string;
  columns: string[];
  rows: (string | number)[][];
  children: ReactNode;
  footnote?: ReactNode;
}) {
  const [showTable, setShowTable] = useState(false);
  const descriptionId = useId();

  return (
    <figure className="m-0">
      <figcaption className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">{title}</h3>
          <p id={descriptionId} className="mt-0.5 max-w-prose text-2xs muted">{description}</p>
        </div>
        <button
          type="button"
          className="btn px-2 py-1 text-2xs no-print"
          aria-expanded={showTable}
          onClick={() => setShowTable((v) => !v)}
        >
          {showTable ? "Show chart" : "Show data table"}
        </button>
      </figcaption>

      {showTable ? (
        <ChartDataTable caption={title} columns={columns} rows={rows} />
      ) : (
        <div aria-describedby={descriptionId} role="img" aria-label={`${title}. ${description}`}>
          {children}
        </div>
      )}

      {footnote ? <p className="mt-2 text-2xs muted">{footnote}</p> : null}
    </figure>
  );
}

export function ChartDataTable({
  caption,
  columns,
  rows,
}: {
  caption: string;
  columns: string[];
  rows: (string | number)[][];
}) {
  return (
    <div className="max-h-80 overflow-auto rounded border border-[rgb(var(--border))]">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 bg-[rgb(var(--surface-sunken))]">
          <tr>
            {columns.map((column) => (
              <th key={column} className="th" scope="col">{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className="td tabular">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Shared plotting geometry, so every chart has identical padding and axes. */
export const PLOT = { width: 520, height: 300, left: 46, right: 12, top: 12, bottom: 34 };

export function plotScales(xDomain: [number, number], yDomain: [number, number]) {
  const innerWidth = PLOT.width - PLOT.left - PLOT.right;
  const innerHeight = PLOT.height - PLOT.top - PLOT.bottom;
  const [x0, x1] = xDomain;
  const [y0, y1] = yDomain;
  return {
    x: (value: number) => PLOT.left + ((value - x0) / (x1 - x0 || 1)) * innerWidth,
    y: (value: number) => PLOT.top + innerHeight - ((value - y0) / (y1 - y0 || 1)) * innerHeight,
    innerWidth,
    innerHeight,
  };
}

export function Axes({
  xLabel,
  yLabel,
  xTicks,
  yTicks,
  scales,
  formatX = String,
  formatY = String,
}: {
  xLabel: string;
  yLabel: string;
  xTicks: number[];
  yTicks: number[];
  scales: ReturnType<typeof plotScales>;
  /** Tick label formatters. A time axis whose ticks print epoch milliseconds
   *  is not an axis, so charts on a time domain must pass one. */
  formatX?: (value: number) => string;
  formatY?: (value: number) => string;
}) {
  return (
    <g className="text-[10px]" fill="currentColor">
      <line
        x1={PLOT.left} y1={PLOT.top + scales.innerHeight}
        x2={PLOT.left + scales.innerWidth} y2={PLOT.top + scales.innerHeight}
        stroke="currentColor" strokeOpacity={0.35}
      />
      <line
        x1={PLOT.left} y1={PLOT.top}
        x2={PLOT.left} y2={PLOT.top + scales.innerHeight}
        stroke="currentColor" strokeOpacity={0.35}
      />
      {xTicks.map((tick) => (
        <g key={`x${tick}`}>
          <line
            x1={scales.x(tick)} y1={PLOT.top + scales.innerHeight}
            x2={scales.x(tick)} y2={PLOT.top + scales.innerHeight + 4}
            stroke="currentColor" strokeOpacity={0.4}
          />
          <text x={scales.x(tick)} y={PLOT.top + scales.innerHeight + 15} textAnchor="middle" fillOpacity={0.7}>
            {formatX(tick)}
          </text>
        </g>
      ))}
      {yTicks.map((tick) => (
        <g key={`y${tick}`}>
          <line
            x1={PLOT.left - 4} y1={scales.y(tick)} x2={PLOT.left} y2={scales.y(tick)}
            stroke="currentColor" strokeOpacity={0.4}
          />
          <line
            x1={PLOT.left} y1={scales.y(tick)} x2={PLOT.left + scales.innerWidth} y2={scales.y(tick)}
            stroke="currentColor" strokeOpacity={0.12}
          />
          <text x={PLOT.left - 7} y={scales.y(tick) + 3} textAnchor="end" fillOpacity={0.7}>
            {formatY(tick)}
          </text>
        </g>
      ))}
      <text x={PLOT.left + scales.innerWidth / 2} y={PLOT.height - 2} textAnchor="middle" fillOpacity={0.75}>
        {xLabel}
      </text>
      <text
        transform={`rotate(-90 12 ${PLOT.top + scales.innerHeight / 2})`}
        x={12} y={PLOT.top + scales.innerHeight / 2}
        textAnchor="middle" fillOpacity={0.75}
      >
        {yLabel}
      </text>
    </g>
  );
}

export function Svg({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox={`0 0 ${PLOT.width} ${PLOT.height}`}
      className="w-full"
      style={{ maxHeight: 320 }}
      aria-hidden
    >
      {children}
    </svg>
  );
}
