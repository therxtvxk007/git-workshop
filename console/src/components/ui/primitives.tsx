import { useState, type ReactNode } from "react";
import clsx from "clsx";
import {
  STATUS_CLASSES,
  STATUS_DESCRIPTIONS,
  STATUS_LABELS,
  formatInterval,
  formatProbability,
  probabilityColor,
  probabilityTextColor,
} from "@/lib/format";
import type { ForecastStatus, Interval } from "@/lib/api/types";

export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={clsx("card", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-2 border-b border-[rgb(var(--border))] px-4 py-3">
          <div>
            {title ? <h2 className="text-sm font-semibold">{title}</h2> : null}
            {subtitle ? <p className="mt-0.5 text-2xs muted">{subtitle}</p> : null}
          </div>
          {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function StatusBadge({ status, size = "sm" }: { status: ForecastStatus; size?: "sm" | "lg" }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded border font-semibold uppercase tracking-wide",
        STATUS_CLASSES[status],
        size === "lg" ? "px-2.5 py-1 text-xs" : "px-1.5 py-0.5 text-2xs",
      )}
      title={STATUS_DESCRIPTIONS[status]}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

/**
 * A probability with its interval.
 *
 * The bar is a redundant encoding, never the only one: the number is always
 * present, and the interval is drawn as a span rather than an error bar so a
 * wide interval looks wide at a glance. `abstain` and `insufficient_evidence`
 * forecasts pass `interval={null}` and get a hatched bar instead of a
 * confident-looking one.
 */
export function ProbabilityBar({
  value,
  interval,
  baseRate,
  compact = false,
}: {
  value: number;
  interval?: Interval | null;
  baseRate?: number | null;
  compact?: boolean;
}) {
  const pct = Math.min(100, Math.max(0, value * 100));
  return (
    <div className={compact ? "w-32" : "w-full"}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="tabular text-sm font-semibold">{formatProbability(value)}</span>
        {!compact && interval !== undefined ? (
          <span className="tabular text-2xs muted">{formatInterval(interval)}</span>
        ) : null}
      </div>
      <div
        className="relative mt-1 h-2 overflow-hidden rounded-full bg-[rgb(var(--surface-sunken))]"
        role="img"
        aria-label={`Probability ${formatProbability(value)}${
          interval ? `, ${formatInterval(interval)} interval` : ", no interval"
        }`}
      >
        {interval ? (
          <div
            className="absolute inset-y-0 rounded-full bg-uncertainty-400/35"
            style={{
              left: `${interval.lower * 100}%`,
              width: `${Math.max(1, (interval.upper - interval.lower) * 100)}%`,
            }}
          />
        ) : (
          <div
            className="absolute inset-0 opacity-40"
            style={{
              backgroundImage:
                "repeating-linear-gradient(45deg, rgb(246 165 36 / 0.6) 0 4px, transparent 4px 8px)",
            }}
            title="No interval was produced for this forecast."
          />
        )}
        <div
          className="absolute inset-y-0 w-[3px] rounded"
          style={{ left: `calc(${pct}% - 1.5px)`, background: probabilityColor(value) }}
        />
        {baseRate !== undefined && baseRate !== null ? (
          <div
            className="absolute inset-y-0 w-px bg-[rgb(var(--text-muted))]"
            style={{ left: `${baseRate * 100}%` }}
            title={`Base rate ${formatProbability(baseRate)}`}
          />
        ) : null}
      </div>
    </div>
  );
}

/** A colour swatch for the ramp. Always paired with the printed number. */
export function ProbabilitySwatch({ value }: { value: number }) {
  return (
    <span
      className="tabular inline-block min-w-[3.25rem] rounded px-1.5 py-0.5 text-center text-2xs font-semibold"
      style={{ background: probabilityColor(value), color: probabilityTextColor(value) }}
    >
      {formatProbability(value)}
    </span>
  );
}

/**
 * A copyable provenance value.
 *
 * Provenance is only useful if it can be pasted into an issue, so every hash,
 * run id and config digest is one click from the clipboard.
 */
export function CopyChip({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="chip max-w-full hover:bg-navy-100 dark:hover:bg-navy-800"
      onClick={() => {
        navigator.clipboard?.writeText(value).then(
          () => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1400);
          },
          () => setCopied(false),
        );
      }}
      title={`Copy ${label}: ${value}`}
    >
      <span className="muted">{label}</span>
      <span className="truncate">{value}</span>
      <span aria-live="polite" className="ml-1">{copied ? "copied" : "⧉"}</span>
    </button>
  );
}

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: T; label: string; count?: number }[];
  active: T;
  onChange: (id: T) => void;
}) {
  return (
    <div role="tablist" className="flex flex-wrap gap-1 border-b border-[rgb(var(--border))]">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          type="button"
          aria-selected={active === tab.id}
          onClick={() => onChange(tab.id)}
          className={clsx(
            "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors",
            active === tab.id
              ? "border-navy-500 text-navy-700 dark:text-navy-200"
              : "border-transparent muted hover:text-[rgb(var(--text))]",
          )}
        >
          {tab.label}
          {tab.count !== undefined ? <span className="ml-1.5 tabular text-2xs">({tab.count})</span> : null}
        </button>
      ))}
    </div>
  );
}

export function Drawer({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" aria-label={title}>
      <button
        type="button"
        aria-label="Close"
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
      />
      <div className="relative z-10 flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-[rgb(var(--border))] bg-[rgb(var(--surface))] shadow-2xl">
        <header className="sticky top-0 flex items-center justify-between gap-4 border-b border-[rgb(var(--border))] bg-[rgb(var(--surface))] px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button type="button" className="btn px-2 py-1" onClick={onClose}>Close</button>
        </header>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

export function DefinitionList({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
      {items.map((item) => (
        <div key={item.label} className="min-w-0">
          <dt className="label">{item.label}</dt>
          <dd className="mt-0.5 break-words text-sm">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Callout({
  tone = "neutral",
  title,
  children,
}: {
  tone?: "neutral" | "uncertainty" | "alert";
  title?: string;
  children: ReactNode;
}) {
  const cls =
    tone === "alert"
      ? "border-alert-500/40 bg-alert-500/5"
      : tone === "uncertainty"
        ? "border-uncertainty-400/40 bg-uncertainty-400/10"
        : "border-[rgb(var(--border))] bg-[rgb(var(--surface-sunken))]";
  return (
    <div className={clsx("rounded-md border px-3 py-2 text-sm", cls)}>
      {title ? <p className="font-semibold">{title}</p> : null}
      <div className={clsx(title && "mt-1", "muted")}>{children}</div>
    </div>
  );
}
