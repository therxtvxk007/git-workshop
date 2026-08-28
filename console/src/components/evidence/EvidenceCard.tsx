import clsx from "clsx";
import { formatProbability, formatRelativeToCutoff, formatUtc } from "@/lib/format";
import type { EvidenceItem, Stance } from "@/lib/api/types";

const STANCE_LABEL: Record<Stance, string> = {
  supports: "Supports",
  contradicts: "Contradicts",
  context: "Context",
};

const STANCE_CLASS: Record<Stance, string> = {
  supports: "border-navy-500/40 bg-navy-500/10",
  contradicts: "border-uncertainty-400/40 bg-uncertainty-400/10",
  context: "border-[rgb(var(--border))] bg-[rgb(var(--surface-sunken))]",
};

/**
 * One evidence item.
 *
 * Three labels here are not decoration. `post_cutoff` marks material the model
 * was not allowed to see — shown, because an analyst needs to know what the
 * model missed, and labelled, because it must never be read as an input.
 * `syndicated` marks a rewrite of another item, so five headlines do not read
 * as five sources. `restricted` marks an item whose body the licence does not
 * let us redistribute, named rather than dropped.
 */
export function EvidenceCard({
  item,
  cutoffAt,
  onOpen,
  active,
}: {
  item: EvidenceItem;
  cutoffAt: string;
  onOpen?: (item: EvidenceItem) => void;
  active?: boolean;
}) {
  return (
    <article
      className={clsx(
        "rounded-lg border p-3 transition-colors",
        active ? "border-navy-500 ring-1 ring-navy-500/40" : "border-[rgb(var(--border))]",
        item.post_cutoff && "border-uncertainty-400/60 bg-uncertainty-400/5",
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={clsx("chip", STANCE_CLASS[item.stance])}>{STANCE_LABEL[item.stance]}</span>
        <span className="chip">{item.source_name}</span>
        <span className="chip" title="Source reliability, as scored by the ingestion layer">
          rel {formatProbability(item.reliability)}
        </span>
        {item.cluster_size > 1 ? (
          <span className="chip" title="Independence cluster: these items are not independent evidence.">
            cluster of {item.cluster_size}
          </span>
        ) : null}
        {item.syndication_of ? (
          <span className="chip border-uncertainty-400/50" title={`Rewrite of ${item.syndication_of}`}>
            syndicated
          </span>
        ) : null}
        {item.access === "restricted" ? (
          <span className="chip border-uncertainty-400/50">restricted</span>
        ) : null}
        {item.post_cutoff ? (
          <span
            className="chip border-uncertainty-400/60 bg-uncertainty-400/20 font-semibold"
            title="Observed after the cutoff. The model did not and could not use this."
          >
            post-cutoff
          </span>
        ) : null}
      </div>

      <p className="mt-2 text-sm font-medium">{item.claim}</p>

      {item.access === "restricted" ? (
        <p className="mt-1 text-2xs muted">
          The full text is not redistributable under this source’s licence ({item.license}). The
          claim, stance and timing are shown; the body is withheld at the API, not blurred here.
        </p>
      ) : item.body ? (
        <p className="mt-1 line-clamp-2 text-sm muted">{item.body}</p>
      ) : null}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs muted">
        <span title={formatUtc(item.first_observed_at)}>
          observed {formatRelativeToCutoff(item.first_observed_at, cutoffAt)}
        </span>
        <span>retrieved {formatUtc(item.retrieved_at)}</span>
        {onOpen ? (
          <button type="button" className="underline" onClick={() => onOpen(item)}>
            Open detail
          </button>
        ) : null}
      </div>
    </article>
  );
}

/**
 * The extracted span, highlighted in its surrounding text.
 *
 * Rendered by slicing the body rather than by injecting markup, so a source
 * document can never introduce HTML into this console.
 */
export function SpanHighlight({ item }: { item: EvidenceItem }) {
  if (!item.body) return null;
  const start = item.span_start ?? 0;
  const end = Math.min(item.span_end ?? item.body.length, item.body.length);
  if (start >= end) return <p className="text-sm">{item.body}</p>;
  return (
    <p className="text-sm leading-relaxed">
      {item.body.slice(0, start)}
      <mark className="rounded bg-uncertainty-300/40 px-0.5">{item.body.slice(start, end)}</mark>
      {item.body.slice(end)}
    </p>
  );
}
