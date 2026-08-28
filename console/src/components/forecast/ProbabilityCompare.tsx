import { ProbabilityBar, StatusBadge } from "@/components/ui/primitives";
import { formatProbability, formatProbabilityDelta, formatCoverage, STATUS_DESCRIPTIONS } from "@/lib/format";
import type { ForecastDetail } from "@/lib/api/types";

/**
 * Raw, calibrated and base rate on one axis.
 *
 * Showing the calibrated number alone would hide the most important fact about
 * this build: calibration is `identity@uncalibrated`, so raw and calibrated are
 * the same value. Putting them side by side makes that visible instead of
 * letting the word "calibrated" do work it has not earned.
 */
export function ProbabilityCompare({ forecast }: { forecast: ForecastDetail }) {
  const identical = Math.abs(forecast.raw_probability - forecast.calibrated_probability) < 1e-9;
  const vsBase =
    forecast.base_rate === null ? null : forecast.calibrated_probability - forecast.base_rate;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <p className="label">Calibrated probability</p>
          <p className="tabular text-3xl font-semibold">
            {formatProbability(forecast.calibrated_probability)}
          </p>
          <p className="text-2xs muted">
            {forecast.interval
              ? `${formatCoverage(forecast.interval)} shown as the band below`
              : "No interval was produced for this forecast"}
          </p>
        </div>
        <div className="ml-auto text-right">
          <StatusBadge status={forecast.status} size="lg" />
          <p className="mt-1 max-w-[22rem] text-2xs muted">{STATUS_DESCRIPTIONS[forecast.status]}</p>
        </div>
      </div>

      <ProbabilityBar
        value={forecast.calibrated_probability}
        interval={forecast.interval}
        baseRate={forecast.base_rate}
      />

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <dt className="label">Raw</dt>
          <dd className="tabular text-sm">{formatProbability(forecast.raw_probability)}</dd>
        </div>
        <div>
          <dt className="label">Calibrated</dt>
          <dd className="tabular text-sm">{formatProbability(forecast.calibrated_probability)}</dd>
        </div>
        <div>
          <dt className="label">Base rate</dt>
          <dd className="tabular text-sm">
            {formatProbability(forecast.base_rate)}
            {vsBase !== null ? (
              <span className="ml-1 text-2xs muted">({formatProbabilityDelta(vsBase)})</span>
            ) : null}
          </dd>
        </div>
        <div>
          <dt className="label">Epistemic uncertainty</dt>
          <dd className="tabular text-sm">{formatProbability(forecast.epistemic_uncertainty)}</dd>
        </div>
      </dl>

      {identical ? (
        <p className="rounded border border-uncertainty-400/40 bg-uncertainty-400/10 px-3 py-2 text-2xs">
          Raw and calibrated are identical because this run used{" "}
          <code>{forecast.provenance.calibration}</code>. The word “calibrated” here names the
          field, not a property of the number: it has not been mapped onto observed frequencies.
        </p>
      ) : null}
    </div>
  );
}
