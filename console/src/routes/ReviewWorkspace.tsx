import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Card, Callout, DefinitionList } from "@/components/ui/primitives";
import { TaskStateBadge } from "@/components/review/TaskStateBadge";
import { EvidenceCard } from "@/components/evidence/EvidenceCard";
import { ErrorState, LoadingState } from "@/components/states/StateViews";
import { EVENT_FAMILY_LABELS, formatProbability, formatUtc, nowUtc } from "@/lib/format";
import { useReviewTask } from "@/lib/queries";
import { cloud, type ReviewDecisionValue, type StoredReview } from "@/lib/cloud";
import { useSession } from "@/components/SessionProvider";

const DECISIONS: { value: ReviewDecisionValue; label: string; hint: string }[] = [
  { value: "accept", label: "Accept", hint: "The claim is well supported by the evidence available at the cutoff." },
  { value: "correct", label: "Correct", hint: "Supported, but at a materially different probability. Give yours." },
  { value: "reject", label: "Reject", hint: "The evidence does not support the claim, or contradicts it." },
];

const MIN_RATIONALE = 20;

export function ReviewWorkspace() {
  const { taskId } = useParams<{ taskId: string }>();
  const task = useReviewTask(taskId);
  const { user } = useSession();

  const [decision, setDecision] = useState<ReviewDecisionValue | null>(null);
  const [probability, setProbability] = useState("0.30");
  const [rationale, setRationale] = useState("");
  const [evidenceIds, setEvidenceIds] = useState<string[]>([]);
  const [peers, setPeers] = useState<StoredReview[]>([]);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [disputeReason, setDisputeReason] = useState("");
  const startedAt = useRef(nowUtc().getTime());

  const refreshPeers = useMemo(
    () => async () => {
      if (!taskId) return;
      setPeers(await cloud.listReviews(taskId));
    },
    [taskId],
  );

  useEffect(() => {
    void refreshPeers();
  }, [refreshPeers]);

  const ownReview = peers.find((p) => p.reviewerId === user?.id) ?? null;
  const unblinded = !!ownReview || submitted;

  if (task.isLoading) return <LoadingState label="Loading task" />;
  if (task.error) return <ErrorState error={task.error} />;
  if (!task.data) return null;

  const detail = task.data;
  const rationaleTooShort = rationale.trim().length < MIN_RATIONALE;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!decision || rationaleTooShort) return;
    setBusy(true);
    setError(null);
    try {
      await cloud.submitReview({
        taskId: detail.task_id,
        decision,
        correctedProbability: decision === "correct" ? Number(probability) : null,
        rationale: rationale.trim(),
        evidenceIds,
        sawSuggestion: detail.suggestion_label !== null,
        timeSpentSeconds: Math.round((nowUtc().getTime() - startedAt.current) / 1000),
      });
      setSubmitted(true);
      await refreshPeers();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Submission failed.");
    } finally {
      setBusy(false);
    }
  };

  const peerReviews = peers.filter((p) => p.reviewerId !== user?.id);
  const disagreement =
    unblinded && ownReview && peerReviews.some((p) => p.decision !== ownReview.decision);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <nav className="text-2xs muted">
            <Link className="underline" to="/review">Review queue</Link>
          </nav>
          <h1 className="mt-1 text-lg font-semibold">
            {detail.district_name}
            <span className="muted font-normal"> · {EVENT_FAMILY_LABELS[detail.event_family]}</span>
          </h1>
        </div>
        <TaskStateBadge state={detail.state_} />
      </header>

      {!unblinded ? (
        <Callout title="Blinded">
          The model’s probability, status and identity are not in the payload behind this page — not
          hidden by the interface, absent from the response. Peer reviews are withheld by an RLS
          policy until your own review row exists.
        </Callout>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card title="The claim">
          <p className="text-sm font-medium">{detail.claim}</p>
          <div className="mt-3">
            <DefinitionList
              items={[
                { label: "Cutoff", value: formatUtc(detail.cutoff_at) },
                { label: "Horizon", value: `${detail.horizon_days} days` },
                { label: "State", value: detail.state },
                { label: "Evidence available", value: String(detail.evidence.length) },
              ]}
            />
          </div>

          {detail.suggestion_label ? (
            <Callout tone="uncertainty" title="Machine suggestion — labelled">
              <p>{detail.suggestion_label}</p>
              <p className="mt-1">
                Shown only after your submission, and recorded on your review as
                <code className="mx-1">saw_suggestion</code>, so any anchoring effect can be
                measured later rather than assumed away.
              </p>
            </Callout>
          ) : null}

          <h3 className="mt-4 text-sm font-semibold">Evidence at the cutoff</h3>
          <p className="text-2xs muted">
            Post-cutoff and non-redistributable items are excluded from this set by the API. You
            are seeing what the model saw.
          </p>
          <div className="mt-2 space-y-2">
            {detail.evidence.map((item) => (
              <label key={item.evidence_id} className="block cursor-pointer">
                <span className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    className="mt-3"
                    disabled={unblinded}
                    checked={evidenceIds.includes(item.evidence_id)}
                    onChange={(e) =>
                      setEvidenceIds((ids) =>
                        e.target.checked
                          ? [...ids, item.evidence_id]
                          : ids.filter((id) => id !== item.evidence_id),
                      )
                    }
                  />
                  <span className="min-w-0 flex-1">
                    <EvidenceCard item={item} cutoffAt={detail.cutoff_at} />
                  </span>
                </span>
              </label>
            ))}
          </div>
        </Card>

        <div className="space-y-4">
          <Card title="Your judgement" subtitle={unblinded ? "Submitted — immutable" : "Not yet submitted"}>
            {unblinded && ownReview ? (
              <DefinitionList
                items={[
                  { label: "Decision", value: ownReview.decision },
                  {
                    label: "Your probability",
                    value: ownReview.correctedProbability === null
                      ? "not applicable"
                      : formatProbability(ownReview.correctedProbability),
                  },
                  { label: "Submitted", value: formatUtc(ownReview.submittedAt) },
                  { label: "Rationale", value: ownReview.rationale },
                ]}
              />
            ) : (
              <form className="space-y-3" onSubmit={submit}>
                <fieldset>
                  <legend className="label">Decision</legend>
                  <div className="mt-1 space-y-1">
                    {DECISIONS.map((option) => (
                      <label key={option.value} className="flex items-start gap-2 text-sm">
                        <input
                          type="radio"
                          name="decision"
                          className="mt-1"
                          value={option.value}
                          checked={decision === option.value}
                          onChange={() => setDecision(option.value)}
                        />
                        <span>
                          <span className="font-medium">{option.label}</span>
                          <span className="block text-2xs muted">{option.hint}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </fieldset>

                {decision === "correct" ? (
                  <div>
                    <label className="label" htmlFor="review-probability">
                      Your probability ({formatProbability(Number(probability))})
                    </label>
                    <input
                      id="review-probability"
                      type="range"
                      min={0}
                      max={1}
                      step={0.01}
                      className="mt-2 w-full"
                      value={probability}
                      onChange={(e) => setProbability(e.target.value)}
                    />
                  </div>
                ) : null}

                <div>
                  <label className="label" htmlFor="review-rationale">Rationale</label>
                  <textarea
                    id="review-rationale"
                    className="field mt-1 h-28"
                    value={rationale}
                    onChange={(e) => setRationale(e.target.value)}
                    placeholder="Which evidence drove this, and what would change your mind?"
                    aria-describedby="rationale-hint"
                  />
                  <p id="rationale-hint" className="mt-1 text-2xs muted">
                    At least {MIN_RATIONALE} characters, enforced by a database constraint as well
                    as here. A review with no reasoning cannot be adjudicated later.
                  </p>
                </div>

                {error ? (
                  <p role="alert" className="rounded border border-alert-500/40 bg-alert-500/5 px-3 py-2 text-sm">
                    {error}
                  </p>
                ) : null}

                <Callout tone="uncertainty" title="Submission is final">
                  There is no update or delete policy on the reviews table. A reviewer who can edit
                  a submitted review after seeing a peer’s can manufacture agreement. Corrections
                  happen through adjudication, which appends a new record.
                </Callout>

                <button
                  type="submit"
                  className="btn-primary w-full"
                  disabled={busy || !decision || rationaleTooShort}
                >
                  {busy ? "Submitting…" : "Submit review (final)"}
                </button>
              </form>
            )}
          </Card>

          {unblinded ? (
            <Card title="Peer reviews" subtitle="Visible because your own review is in">
              {peerReviews.length === 0 ? (
                <p className="text-sm muted">
                  No other reviewer has submitted yet. This task needs two independent reviews
                  before it can be adjudicated.
                </p>
              ) : (
                <ul className="space-y-3">
                  {peerReviews.map((peer) => (
                    <li key={peer.id} className="rounded border border-[rgb(var(--border))] p-3">
                      <p className="text-sm font-medium">
                        {peer.reviewerLabel}: {peer.decision}
                        {peer.correctedProbability !== null
                          ? ` at ${formatProbability(peer.correctedProbability)}`
                          : ""}
                      </p>
                      <p className="mt-1 text-sm muted">{peer.rationale}</p>
                      <p className="mt-1 text-2xs muted">{formatUtc(peer.submittedAt)}</p>
                    </li>
                  ))}
                </ul>
              )}

              {disagreement ? (
                <div className="mt-4 border-t border-[rgb(var(--border))] pt-3">
                  <Callout tone="uncertainty" title="The reviewers disagree">
                    Raise a dispute to send this to adjudication. Neither review is altered; the
                    adjudication is appended alongside them.
                  </Callout>
                  <textarea
                    className="field mt-2 h-20"
                    aria-label="Dispute reason"
                    placeholder="Why does this need adjudication?"
                    value={disputeReason}
                    onChange={(e) => setDisputeReason(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn mt-2"
                    disabled={disputeReason.trim().length < MIN_RATIONALE}
                    onClick={() => {
                      void cloud.raiseDispute(detail.task_id, disputeReason.trim()).then(() => {
                        setDisputeReason("");
                      });
                    }}
                  >
                    Raise dispute
                  </button>
                </div>
              ) : null}
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}
