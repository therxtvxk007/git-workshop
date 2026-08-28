import { Link } from "react-router-dom";
import { Card, Callout } from "@/components/ui/primitives";
import { TaskStateBadge } from "@/components/review/TaskStateBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/states/StateViews";
import { EVENT_FAMILY_LABELS, formatUtc } from "@/lib/format";
import { useReviewTasks } from "@/lib/queries";

export function ReviewQueue() {
  const tasks = useReviewTasks();

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-lg font-semibold">Review queue</h1>
        <p className="mt-1 max-w-prose text-sm muted">
          Each task is judged by two reviewers independently. Until you submit, you cannot see the
          other reviewer’s answer — and neither can the interface, because the database does not
          return it.
        </p>
      </header>

      <Callout title="What you will and will not see">
        A task shows the claim, the horizon and the evidence available at the cutoff. It does not
        show the model’s probability, its status or which generator proposed it. Anchoring a human
        judgement on the model’s answer is how an annotation set stops being an independent
        measurement of anything.
      </Callout>

      {tasks.isLoading ? <LoadingState label="Loading queue" /> : null}
      {tasks.error ? <ErrorState error={tasks.error} /> : null}

      {tasks.data ? (
        tasks.data.length === 0 ? (
          <EmptyState title="No tasks assigned to you">
            Assignments are made by an administrator.
          </EmptyState>
        ) : (
          <Card>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] border-collapse">
                <caption className="sr-only">Review tasks assigned to you</caption>
                <thead className="bg-[rgb(var(--surface-sunken))]">
                  <tr>
                    <th className="th">District</th>
                    <th className="th">Family</th>
                    <th className="th">State</th>
                    <th className="th">Reviews in</th>
                    <th className="th">Due</th>
                    <th className="th">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {tasks.data.map((task) => (
                    <tr key={task.task_id} className="hover:bg-[rgb(var(--surface-sunken))]">
                      <td className="td font-medium">{task.district_name}</td>
                      <td className="td">{EVENT_FAMILY_LABELS[task.event_family]}</td>
                      <td className="td"><TaskStateBadge state={task.task_state} /></td>
                      <td className="td tabular">
                        {task.reviews_submitted} / 2
                        {task.own_review_submitted ? (
                          <span className="ml-1 text-2xs muted">(yours in)</span>
                        ) : null}
                      </td>
                      <td className="td text-2xs">{formatUtc(task.due_at)}</td>
                      <td className="td">
                        <Link className="btn px-2 py-1 text-xs" to={`/review/${task.task_id}`}>
                          {task.own_review_submitted ? "View" : "Review"}
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )
      ) : null}
    </div>
  );
}
