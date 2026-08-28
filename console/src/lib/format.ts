import type { EventFamily, ForecastStatus, Interval } from "@/lib/api/types";

/**
 * Presentation rules.
 *
 * Formatting is centralised because precision is an editorial decision here,
 * not a styling one. `0.6231` rendered as "62.31%" claims four significant
 * figures from a model whose calibration is literally recorded as
 * `identity@uncalibrated`. Every probability in this console goes through
 * `formatProbability`, which refuses to imply precision the model does not have.
 */

/** The single clock. Wrapped so tests can freeze it and cutoff logic stays honest. */
export function nowUtc(): Date {
  // eslint-disable-next-line no-restricted-globals
  return new Date();
}

/**
 * Probability as a percentage.
 *
 *  - at or above 10%: whole percent ("62%")
 *  - below 10%: one decimal ("4.3%"), where a point of resolution still means
 *    something against a ~7% base rate
 *  - the extremes are clamped to "<0.1%" and ">99.9%" rather than rendered as
 *    0% or 100%, because a model that never observed the event should not be
 *    shown asserting impossibility.
 */
export function formatProbability(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const pct = value * 100;
  if (pct > 0 && pct < 0.1) return "<0.1%";
  if (pct < 100 && pct > 99.9) return ">99.9%";
  if (pct === 0) return "0%";
  if (pct === 100) return "100%";
  // The threshold is 9.95, not 10, because the branches must agree after
  // rounding: at 9.99 the one-decimal branch prints "10.0%" while 10 itself
  // prints "10%", and two renderings of the same magnitude read as two
  // different precisions.
  return pct >= 9.95 ? `${Math.round(pct)}%` : `${pct.toFixed(1)}%`;
}

/** Percentage-point delta, always signed, for comparisons and scenarios. */
export function formatProbabilityDelta(delta: number): string {
  const pts = delta * 100;
  const sign = pts > 0 ? "+" : pts < 0 ? "−" : "±";
  const magnitude = Math.abs(pts);
  return `${sign}${magnitude >= 10 ? Math.round(magnitude) : magnitude.toFixed(1)} pp`;
}

/** A two-sided interval. Never abbreviated to one bound. */
export function formatInterval(interval: Interval | null | undefined): string {
  if (!interval) return "no interval";
  return `${formatProbability(interval.lower)} – ${formatProbability(interval.upper)}`;
}

export function formatCoverage(interval: Interval | null | undefined): string {
  if (!interval) return "";
  return `${Math.round(interval.coverage * 100)}% interval`;
}

/**
 * Timestamps are UTC, always, with the zone in the string.
 *
 * A console whose cutoff reads "15 Jan, 00:00" in the reader's local zone will
 * eventually have somebody compare it to a UTC cutoff and conclude the model
 * saw the future.
 */
export function formatUtc(value: string | Date | null | undefined, opts?: { seconds?: boolean }): string {
  if (!value) return "—";
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "invalid date";
  const pad = (n: number) => String(n).padStart(2, "0");
  const base =
    `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ` +
    `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
  return `${base}${opts?.seconds ? `:${pad(date.getUTCSeconds())}` : ""} UTC`;
}

export function formatUtcDate(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "invalid date";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

/** Signed, coarse elapsed time. "2 d before cutoff", "6 h after cutoff". */
export function formatRelativeToCutoff(value: string, cutoff: string): string {
  const delta = Date.parse(value) - Date.parse(cutoff);
  const abs = Math.abs(delta);
  const unit =
    abs >= 86_400_000
      ? `${Math.round(abs / 86_400_000)} d`
      : abs >= 3_600_000
        ? `${Math.round(abs / 3_600_000)} h`
        : `${Math.max(1, Math.round(abs / 60_000))} min`;
  if (abs < 60_000) return "at cutoff";
  return delta < 0 ? `${unit} before cutoff` : `${unit} after cutoff`;
}

/* ------------------------------------------------------------- statuses */

export const STATUS_LABELS: Record<ForecastStatus, string> = {
  alert: "Alert",
  watch: "Watch",
  monitor: "Monitor",
  abstain: "Abstain",
  insufficient_evidence: "Insufficient evidence",
};

export const STATUS_DESCRIPTIONS: Record<ForecastStatus, string> = {
  alert: "Calibrated risk and evidence quality justify immediate analyst review.",
  watch: "Material risk, confirmation incomplete.",
  monitor: "Weak, novel or early signal, retained to protect recall.",
  abstain: "Model conflict or distribution shift makes the probability unreliable.",
  insufficient_evidence: "The candidate exists, but the evidence needed to assess it is unavailable.",
};

/**
 * Status colours. Red belongs to `alert` alone; `abstain` and
 * `insufficient_evidence` are amber because both are statements about
 * uncertainty rather than about risk.
 */
export const STATUS_CLASSES: Record<ForecastStatus, string> = {
  alert: "bg-alert-500/15 text-alert-600 dark:text-alert-300 border-alert-500/40",
  watch: "bg-navy-500/15 text-navy-700 dark:text-navy-200 border-navy-500/40",
  monitor: "bg-navy-400/10 text-navy-600 dark:text-navy-300 border-navy-400/30",
  abstain: "bg-uncertainty-400/15 text-uncertainty-700 dark:text-uncertainty-300 border-uncertainty-400/40",
  insufficient_evidence:
    "bg-uncertainty-300/10 text-uncertainty-700 dark:text-uncertainty-300 border-uncertainty-300/30",
};

export const EVENT_FAMILY_LABELS: Record<EventFamily, string> = {
  civil_unrest: "Civil unrest",
  flood: "Flood",
  drought: "Drought",
  epidemic_signal: "Epidemic signal",
  infrastructure_disruption: "Infrastructure disruption",
  displacement: "Displacement",
};

/* --------------------------------------------------------- probability ramp */

/**
 * `cividis`, sampled at ten stops.
 *
 * Chosen over the usual green-to-red because it stays monotonically ordered
 * under all three common colour-vision deficiencies. Colour is never the only
 * encoding: every call site also prints the number.
 */
const CIVIDIS = [
  "#00224e", "#123570", "#3b496c", "#575d6d", "#707173",
  "#8a8678", "#a59c74", "#c3b369", "#e1cc55", "#fee838",
] as const;

export function probabilityColor(value: number): string {
  const clamped = Math.min(1, Math.max(0, value));
  return CIVIDIS[Math.min(CIVIDIS.length - 1, Math.floor(clamped * CIVIDIS.length))]!;
}

/** Foreground that stays legible on the ramp. Dark swatches need light text. */
export function probabilityTextColor(value: number): string {
  return value < 0.55 ? "#f8fafc" : "#0b1220";
}

export const PROBABILITY_RAMP = CIVIDIS;

/* ------------------------------------------------------------------ misc */

export function formatCount(value: number): string {
  return new Intl.NumberFormat("en-IN").format(value);
}

export function formatMetric(value: number | null, unit: string): string {
  if (value === null) return "not computed";
  if (unit === "probability" || unit === "ratio") return value.toFixed(4);
  if (unit === "logloss") return value.toFixed(4);
  return formatCount(value);
}

export function formatHours(value: number | null): string {
  if (value === null) return "—";
  if (value < 1) return `${Math.round(value * 60)} min`;
  if (value < 48) return `${value.toFixed(1)} h`;
  return `${(value / 24).toFixed(1)} d`;
}

/** Truncate a hash for a chip while keeping it copyable in full elsewhere. */
export function shortHash(hash: string, length = 12): string {
  const body = hash.includes(":") ? hash.slice(hash.indexOf(":") + 1) : hash;
  return body.length <= length ? body : `${body.slice(0, length)}…`;
}
