import { Link } from "react-router-dom";
import { formatCount, formatProbability } from "@/lib/format";
import type { ForecastSummary } from "@/lib/api/types";

/**
 * Headline counts.
 *
 * Deliberately not a single "risk score". Five statuses summarised into one
 * number is exactly the compression that turns a research output into something
 * that looks like a decision, and the retained categories — abstain,
 * insufficient evidence — are the ones a summary always drops first.
 */
export function SummaryCards({
  forecasts,
  underCovered,
}: {
  forecasts: ForecastSummary[];
  underCovered: number | null;
}) {
  const count = (status: ForecastSummary["status"]) =>
    forecasts.filter((f) => f.status === status).length;

  const probabilities = [...forecasts]
    .map((f) => f.calibrated_probability)
    .sort((a, b) => a - b);
  const median =
    probabilities.length === 0
      ? null
      : probabilities[Math.floor(probabilities.length / 2)] ?? null;

  const noInterval = forecasts.filter((f) => f.interval === null).length;

  const cards: { label: string; value: string; note: string; tone?: "alert" | "uncertainty" }[] = [
    {
      label: "Scored district-families",
      value: formatCount(forecasts.length),
      note: "Candidates that survived to a scored forecast at this cutoff.",
    },
    {
      label: "Alert",
      value: formatCount(count("alert")),
      note: "Threshold-based, with no miss-rate guarantee. Not a dispatch list.",
      tone: "alert",
    },
    {
      label: "Watch",
      value: formatCount(count("watch")),
      note: "Material risk with incomplete confirmation.",
    },
    {
      label: "Retained but unscoreable",
      value: formatCount(count("abstain") + count("insufficient_evidence")),
      note: `${count("abstain")} abstentions, ${count("insufficient_evidence")} insufficient evidence. Retained, never deleted.`,
      tone: "uncertainty",
    },
    {
      label: "Median probability",
      value: formatProbability(median),
      note: "Across the current filter. Compare against the base rate, not against zero.",
    },
    {
      label: "Without an interval",
      value: formatCount(noInterval),
      note: "Point estimates the engine could not bound. Read them as ordering, not magnitude.",
      tone: noInterval > 0 ? "uncertainty" : undefined,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
      {cards.map((card) => (
        <div
          key={card.label}
          className={`card p-3 ${
            card.tone === "alert"
              ? "border-alert-500/40"
              : card.tone === "uncertainty"
                ? "border-uncertainty-400/40"
                : ""
          }`}
        >
          <p className="label">{card.label}</p>
          <p className="tabular mt-1 text-2xl font-semibold">{card.value}</p>
          <p className="mt-1 text-2xs muted">{card.note}</p>
        </div>
      ))}
      {underCovered !== null && underCovered > 0 ? (
        <div className="card col-span-2 border-uncertainty-400/40 p-3 lg:col-span-3 xl:col-span-6">
          <p className="text-sm">
            <strong>{underCovered}</strong> district
            {underCovered === 1 ? " is" : "s are"} under-covered by the current sources. A low
            probability there means the evidence is thin, not that the risk is low.{" "}
            <Link className="underline" to="/data-health">
              See data health
            </Link>
            .
          </p>
        </div>
      ) : null}
    </div>
  );
}
