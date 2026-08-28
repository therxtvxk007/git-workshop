import clsx from "clsx";
import type { ReviewTaskState } from "@/lib/api/types";

const LABELS: Record<ReviewTaskState, string> = {
  pending: "Pending",
  in_review: "In review",
  submitted: "Submitted",
  adjudicated: "Adjudicated",
  disputed: "Disputed",
};

const CLASSES: Record<ReviewTaskState, string> = {
  pending: "border-[rgb(var(--border))] bg-[rgb(var(--surface-sunken))]",
  in_review: "border-navy-500/40 bg-navy-500/10",
  submitted: "border-navy-600/50 bg-navy-600/15",
  adjudicated: "border-navy-400/40 bg-navy-400/10",
  // Disputed is amber, not red: two reviewers disagreeing is the process
  // working, not an incident.
  disputed: "border-uncertainty-400/50 bg-uncertainty-400/15",
};

export function TaskStateBadge({ state }: { state: ReviewTaskState }) {
  return (
    <span className={clsx("chip font-semibold uppercase", CLASSES[state])}>{LABELS[state]}</span>
  );
}
