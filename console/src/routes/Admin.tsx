import { useEffect, useState } from "react";
import { Card, Callout, Tabs } from "@/components/ui/primitives";
import { EmptyState, LoadingState } from "@/components/states/StateViews";
import { apiMode } from "@/lib/api/client";
import { formatProbability, formatUtc } from "@/lib/format";
import {
  cloud,
  cloudIsLocal,
  ROLE_ORDER,
  type Adjudication,
  type AppRole,
  type CloudUser,
  type Dispute,
  type ExportRecord,
} from "@/lib/cloud";
import { useSession } from "@/components/SessionProvider";

type TabId = "users" | "disputes" | "exports" | "api";

export function Admin() {
  const { user: me } = useSession();
  const [tab, setTab] = useState<TabId>("users");
  const [users, setUsers] = useState<CloudUser[] | null>(null);
  const [disputes, setDisputes] = useState<Dispute[]>([]);
  const [adjudications, setAdjudications] = useState<Adjudication[]>([]);
  const [exports, setExports] = useState<ExportRecord[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    setUsers(await cloud.listUsers());
    setDisputes(await cloud.listDisputes());
    setAdjudications(await cloud.listAdjudications());
    setExports(await cloud.listExports());
  };

  useEffect(() => {
    void refresh();
  }, []);

  const toggleRole = async (userId: string, role: AppRole, held: boolean) => {
    setError(null);
    try {
      if (held) await cloud.revokeRole(userId, role);
      else await cloud.grantRole(userId, role);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Role change failed.");
    }
  };

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-lg font-semibold">Administration</h1>
        <p className="mt-1 max-w-prose text-sm muted">
          Roles, disputes, the export register and the API configuration in force.
        </p>
      </header>

      <Tabs<TabId>
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "users", label: "Users & roles", count: users?.length },
          { id: "disputes", label: "Disputes", count: disputes.length },
          { id: "exports", label: "Exports", count: exports.length },
          { id: "api", label: "API configuration" },
        ]}
      />

      {error ? (
        <p role="alert" className="rounded border border-alert-500/40 bg-alert-500/5 px-3 py-2 text-sm">
          {error}
        </p>
      ) : null}

      {tab === "users" ? (
        <Card title="Users and roles">
          <Callout tone="uncertainty" title="Roles are authorisation, not preference">
            Roles live in their own table with their own policies. A user cannot grant themselves
            one by editing their profile, and this screen cannot either — every change below is an
            insert or delete that an RLS policy has to approve.
          </Callout>

          {users === null ? (
            <LoadingState label="Loading users" />
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse">
                <caption className="sr-only">Users and the roles they hold</caption>
                <thead className="bg-[rgb(var(--surface-sunken))]">
                  <tr>
                    <th className="th">User</th>
                    {ROLE_ORDER.map((role) => (
                      <th key={role} className="th">{role}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr key={user.id}>
                      <td className="td">
                        <span className="font-medium">{user.displayName}</span>
                        <span className="block text-2xs muted">{user.email || user.id}</span>
                      </td>
                      {ROLE_ORDER.map((role) => {
                        const held = user.roles.includes(role);
                        const isSelfDemotion = user.id === me?.id && role === "administrator" && held;
                        return (
                          <td key={role} className="td">
                            <label className="flex items-center gap-1.5 text-2xs">
                              <input
                                type="checkbox"
                                checked={held}
                                disabled={isSelfDemotion}
                                title={
                                  isSelfDemotion
                                    ? "Removing your own administrator role would lock you out of this screen."
                                    : undefined
                                }
                                onChange={() => void toggleRole(user.id, role, held)}
                              />
                              {held ? "held" : "—"}
                            </label>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      ) : null}

      {tab === "disputes" ? (
        <div className="space-y-4">
          <Card title="Open disputes">
            {disputes.length === 0 ? (
              <EmptyState title="No disputes">
                A dispute is raised when two reviewers disagree and one of them escalates.
              </EmptyState>
            ) : (
              <ul className="space-y-2">
                {disputes.map((dispute) => (
                  <li key={dispute.id} className="rounded border border-uncertainty-400/40 p-3">
                    <p className="text-sm font-medium">{dispute.taskId}</p>
                    <p className="mt-1 text-sm muted">{dispute.reason}</p>
                    <p className="mt-1 text-2xs muted">
                      raised by {dispute.raisedBy} · {formatUtc(dispute.raisedAt)}
                    </p>
                    <AdjudicationForm taskId={dispute.taskId} onDone={() => void refresh()} />
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Adjudications">
            {adjudications.length === 0 ? (
              <EmptyState title="No adjudications recorded" />
            ) : (
              <ul className="space-y-2">
                {adjudications.map((adjudication) => (
                  <li key={adjudication.id} className="rounded border border-[rgb(var(--border))] p-3">
                    <p className="text-sm font-medium">
                      {adjudication.taskId}: {adjudication.decision}
                      {adjudication.finalProbability !== null
                        ? ` at ${formatProbability(adjudication.finalProbability)}`
                        : ""}
                    </p>
                    <p className="mt-1 text-sm muted">{adjudication.rationale}</p>
                    <p className="mt-1 text-2xs muted">{formatUtc(adjudication.adjudicatedAt)}</p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      ) : null}

      {tab === "exports" ? (
        <Card title="Export register" subtitle="Every file this console has produced">
          {exports.length === 0 ? (
            <EmptyState title="No exports recorded" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] border-collapse">
                <caption className="sr-only">Exports produced from this console</caption>
                <thead className="bg-[rgb(var(--surface-sunken))]">
                  <tr>
                    <th className="th">Export</th>
                    <th className="th">Format</th>
                    <th className="th">Rows</th>
                    <th className="th">Cutoff</th>
                    <th className="th">Mode</th>
                    <th className="th">When</th>
                  </tr>
                </thead>
                <tbody>
                  {exports.map((record) => (
                    <tr key={record.id}>
                      <td className="td">
                        {record.exportName}
                        {record.isHypothetical ? (
                          <span className="ml-2 chip border-uncertainty-400/50">hypothetical</span>
                        ) : null}
                      </td>
                      <td className="td uppercase">{record.format}</td>
                      <td className="td tabular">{record.rowCount}</td>
                      <td className="td text-2xs">{formatUtc(record.cutoffAt)}</td>
                      <td className="td uppercase">{record.dataMode}</td>
                      <td className="td text-2xs">{formatUtc(record.createdAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="mt-2 text-2xs muted">
            When a spreadsheet turns up somewhere it should not be, this is how its cutoff,
            snapshot and filters get reconstructed.
          </p>
        </Card>
      ) : null}

      {tab === "api" ? (
        <Card title="API configuration">
          <dl className="grid gap-3 sm:grid-cols-2">
            <div>
              <dt className="label">Adapter mode</dt>
              <dd className="text-sm">{apiMode.mode} — {apiMode.label}</dd>
            </div>
            <div>
              <dt className="label">Base URL</dt>
              <dd className="break-all font-mono text-2xs">{apiMode.baseUrl ?? "not applicable"}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="label">Behaviour</dt>
              <dd className="text-sm">{apiMode.description}</dd>
            </div>
            <div>
              <dt className="label">Persistence</dt>
              <dd className="text-sm">
                {cloudIsLocal ? "Browser local storage (development only)" : "Postgres with RLS"}
              </dd>
            </div>
          </dl>

          <Callout tone="uncertainty" title="Where the API key lives">
            Not here. The browser never holds an engine credential: authenticated REST calls carry
            the signed-in user’s session token, and any engine-side key stays in the server function
            that proxies them. A key shipped to the client is a key published.
          </Callout>
        </Card>
      ) : null}
    </div>
  );
}

function AdjudicationForm({ taskId, onDone }: { taskId: string; onDone: () => void }) {
  const [rationale, setRationale] = useState("");
  const [decision, setDecision] = useState<"accept" | "correct" | "reject">("accept");
  const [probability, setProbability] = useState("0.3");
  const [busy, setBusy] = useState(false);

  return (
    <form
      className="mt-3 space-y-2 border-t border-[rgb(var(--border))] pt-3"
      onSubmit={(event) => {
        event.preventDefault();
        setBusy(true);
        void cloud
          .adjudicate(taskId, decision, decision === "correct" ? Number(probability) : null, rationale.trim())
          .then(() => {
            setRationale("");
            onDone();
          })
          .finally(() => setBusy(false));
      }}
    >
      <div className="flex flex-wrap gap-2">
        <select
          className="field w-36"
          aria-label="Adjudication decision"
          value={decision}
          onChange={(e) => setDecision(e.target.value as typeof decision)}
        >
          <option value="accept">Accept</option>
          <option value="correct">Correct</option>
          <option value="reject">Reject</option>
        </select>
        {decision === "correct" ? (
          <input
            className="field w-28"
            type="number"
            min={0}
            max={1}
            step={0.01}
            aria-label="Final probability"
            value={probability}
            onChange={(e) => setProbability(e.target.value)}
          />
        ) : null}
      </div>
      <textarea
        className="field h-20"
        aria-label="Adjudication rationale"
        placeholder="Why this resolution? Both reviews stay on the record unchanged."
        value={rationale}
        onChange={(e) => setRationale(e.target.value)}
      />
      <button type="submit" className="btn" disabled={busy || rationale.trim().length < 20}>
        {busy ? "Recording…" : "Record adjudication"}
      </button>
    </form>
  );
}
