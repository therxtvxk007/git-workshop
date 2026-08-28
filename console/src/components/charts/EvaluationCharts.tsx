import { Axes, ChartFrame, PLOT, Svg, plotScales } from "./ChartFrame";
import { formatUtcDate } from "@/lib/format";
import type { CurvePoint, ReliabilityBin } from "@/lib/api/types";

const TICKS = [0, 0.2, 0.4, 0.6, 0.8, 1];

export function ReliabilityDiagram({ bins }: { bins: ReliabilityBin[] }) {
  const scales = plotScales([0, 1], [0, 1]);
  const maxCount = Math.max(1, ...bins.map((b) => b.count));

  return (
    <ChartFrame
      title="Reliability"
      description="Observed frequency against mean predicted probability, in ten bins. Points on the diagonal are calibrated; points below it are over-confident."
      columns={["Bin", "Mean predicted", "Observed frequency", "n"]}
      rows={bins.map((b) => [
        `${b.bin_lower.toFixed(1)}–${b.bin_upper.toFixed(1)}`,
        b.mean_predicted.toFixed(4),
        b.observed_frequency.toFixed(4),
        b.count,
      ])}
      footnote="Marker area is proportional to the number of samples in the bin. The upper bins are almost always sparse, so a point far from the diagonal there may be noise rather than miscalibration — which is exactly why the sample count is in the table."
    >
      <Svg>
        <Axes xLabel="Mean predicted probability" yLabel="Observed frequency" xTicks={TICKS} yTicks={TICKS} scales={scales} />
        <line
          x1={scales.x(0)} y1={scales.y(0)} x2={scales.x(1)} y2={scales.y(1)}
          stroke="currentColor" strokeOpacity={0.4} strokeDasharray="4 3"
        />
        {bins.map((bin) => (
          <circle
            key={bin.bin_lower}
            cx={scales.x(bin.mean_predicted)}
            cy={scales.y(bin.observed_frequency)}
            r={3 + 7 * Math.sqrt(bin.count / maxCount)}
            fill="#4a679a"
            fillOpacity={0.65}
            stroke="#1e2c49"
          />
        ))}
      </Svg>
    </ChartFrame>
  );
}

export function PRCurve({ points, positiveRate }: { points: CurvePoint[]; positiveRate: number }) {
  const scales = plotScales([0, 1], [0, 1]);
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${scales.x(p.x)},${scales.y(p.y)}`).join(" ");

  return (
    <ChartFrame
      title="Precision–recall"
      description="Precision against recall across decision thresholds. The dashed line is the no-skill floor, which equals the positive rate."
      columns={["Recall", "Precision"]}
      rows={points.map((p) => [p.x.toFixed(3), p.y.toFixed(4)])}
      footnote={`No-skill precision is ${positiveRate.toFixed(4)} — the base rate. A curve that hugs that line has learned nothing, however impressive its AUC-ROC looks.`}
    >
      <Svg>
        <Axes xLabel="Recall" yLabel="Precision" xTicks={TICKS} yTicks={TICKS} scales={scales} />
        <line
          x1={scales.x(0)} y1={scales.y(positiveRate)} x2={scales.x(1)} y2={scales.y(positiveRate)}
          stroke="currentColor" strokeOpacity={0.5} strokeDasharray="4 3"
        />
        <path d={path} fill="none" stroke="#4a679a" strokeWidth={2} />
      </Svg>
    </ChartFrame>
  );
}

export function BudgetRecallCurve({ points }: { points: CurvePoint[] }) {
  const maxX = Math.max(1, ...points.map((p) => p.x));
  const scales = plotScales([0, maxX], [0, 1]);
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${scales.x(p.x)},${scales.y(p.y)}`).join(" ");
  const xTicks = [0, maxX * 0.25, maxX * 0.5, maxX * 0.75, maxX].map((t) => Math.round(t));

  return (
    <ChartFrame
      title="Budget–recall"
      description="Share of observed events captured, as a function of how many alerts per week an analyst team can actually work."
      columns={["Alerts per week", "Recall"]}
      rows={points.map((p) => [p.x, p.y.toFixed(4)])}
      footnote="This is the curve that decides whether a model is usable. A system with excellent recall at 400 alerts a week and a team that can process 40 has no recall at all."
    >
      <Svg>
        <Axes xLabel="Alert budget (per week)" yLabel="Recall" xTicks={xTicks} yTicks={TICKS} scales={scales} />
        <path d={path} fill="none" stroke="#e0830c" strokeWidth={2} />
      </Svg>
    </ChartFrame>
  );
}

export function AbstentionRiskCurve({ points }: { points: CurvePoint[] }) {
  const maxY = Math.max(0.1, ...points.map((p) => p.y));
  const maxX = Math.max(0.05, ...points.map((p) => p.x));
  const scales = plotScales([0, maxX], [0, maxY]);
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${scales.x(p.x)},${scales.y(p.y)}`).join(" ");

  return (
    <ChartFrame
      title="Abstention–risk"
      description="Error on the retained set as the model is allowed to abstain on more cases. A useful abstention policy drops error quickly."
      columns={["Abstention rate", "Risk on retained set"]}
      rows={points.map((p) => [p.x.toFixed(3), p.y.toFixed(4)])}
      footnote="A flat curve means the model cannot tell which of its own predictions are unreliable, and the abstain status is not buying anything."
    >
      <Svg>
        <Axes
          xLabel="Abstention rate" yLabel="Risk (retained)"
          xTicks={[0, maxX / 2, maxX].map((t) => Number(t.toFixed(2)))}
          yTicks={[0, maxY / 2, maxY].map((t) => Number(t.toFixed(2)))}
          scales={scales}
        />
        <path d={path} fill="none" stroke="#4a679a" strokeWidth={2} />
      </Svg>
    </ChartFrame>
  );
}

/**
 * The forecast trend.
 *
 * The observed-outcome rule is enforced here rather than upstream: a marker is
 * drawn only for points whose `scoreable_from` has passed. Plotting a
 * right-censored non-event as a resolved negative is the single easiest way to
 * make a model look better than it is.
 */
export function HistoricalTrend({
  points,
  now,
}: {
  points: {
    cutoff_at: string;
    calibrated_probability: number;
    interval: { lower: number; upper: number } | null;
    observed_outcome: { occurred: boolean; scoreable_from: string } | null;
  }[];
  now: Date;
}) {
  if (points.length === 0) {
    return <p className="text-sm muted">No earlier cutoffs are available for this district and family.</p>;
  }
  const times = points.map((p) => Date.parse(p.cutoff_at));
  const scales = plotScales([Math.min(...times), Math.max(...times)], [0, 1]);
  const line = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${scales.x(Date.parse(p.cutoff_at))},${scales.y(p.calibrated_probability)}`)
    .join(" ");

  const band = points.filter((p) => p.interval);
  const bandPath =
    band.length > 1
      ? [
          ...band.map((p, i) => `${i === 0 ? "M" : "L"}${scales.x(Date.parse(p.cutoff_at))},${scales.y(p.interval!.upper)}`),
          ...[...band].reverse().map((p) => `L${scales.x(Date.parse(p.cutoff_at))},${scales.y(p.interval!.lower)}`),
          "Z",
        ].join(" ")
      : null;

  const xTicks = [times[0]!, times[Math.floor(times.length / 2)]!, times[times.length - 1]!];

  return (
    <ChartFrame
      title="Probability across cutoffs"
      description="The same district and event family scored at each earlier cutoff, with the interval as a band."
      columns={["Cutoff (UTC)", "Probability", "Interval", "Outcome"]}
      rows={points.map((p) => [
        p.cutoff_at.slice(0, 10),
        p.calibrated_probability.toFixed(4),
        p.interval ? `${p.interval.lower.toFixed(3)}–${p.interval.upper.toFixed(3)}` : "none",
        outcomeLabel(p.observed_outcome, now),
      ])}
      footnote="An outcome marker appears only once the horizon and the reporting delay have both elapsed. Earlier cutoffs are shown as 'not yet scoreable' rather than as non-events, because a right-censored non-event rendered as a miss flatters the model."
    >
      <Svg>
        <Axes
          xLabel="Cutoff (UTC)" yLabel="Calibrated probability"
          xTicks={xTicks} yTicks={TICKS} scales={scales}
          formatX={(value) => formatUtcDate(new Date(value))}
        />
        {bandPath ? <path d={bandPath} fill="#f6a524" fillOpacity={0.18} /> : null}
        <path d={line} fill="none" stroke="#4a679a" strokeWidth={2} />
        {points.map((point) => {
          const outcome = point.observed_outcome;
          const scoreable = outcome && Date.parse(outcome.scoreable_from) <= now.getTime();
          if (!scoreable) return null;
          const x = scales.x(Date.parse(point.cutoff_at));
          return outcome.occurred ? (
            <g key={point.cutoff_at}>
              <line x1={x - 4} y1={PLOT.top + 4} x2={x + 4} y2={PLOT.top + 12} stroke="#dc2626" strokeWidth={2} />
              <line x1={x + 4} y1={PLOT.top + 4} x2={x - 4} y2={PLOT.top + 12} stroke="#dc2626" strokeWidth={2} />
            </g>
          ) : (
            <circle key={point.cutoff_at} cx={x} cy={PLOT.top + 8} r={3.5} fill="none" stroke="currentColor" strokeOpacity={0.6} />
          );
        })}
      </Svg>
    </ChartFrame>
  );
}

function outcomeLabel(
  outcome: { occurred: boolean; scoreable_from: string } | null,
  now: Date,
): string {
  if (!outcome) return "no outcome recorded";
  if (Date.parse(outcome.scoreable_from) > now.getTime()) return "not yet scoreable";
  return outcome.occurred ? "occurred" : "did not occur";
}
