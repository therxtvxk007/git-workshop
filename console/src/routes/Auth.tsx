import { useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useSession } from "@/components/SessionProvider";
import { Callout } from "@/components/ui/primitives";
import { cloudIsLocal } from "@/lib/cloud";

export function Auth() {
  const { user, signIn, signUp } = useSession();
  const location = useLocation();
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) {
    const from = (location.state as { from?: string } | null)?.from ?? "/";
    return <Navigate to={from} replace />;
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "in") await signIn(email, password);
      else await signUp(email, password, displayName);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-md space-y-4 py-8">
      <div className="card p-6">
        <h1 className="text-lg font-semibold">
          {mode === "in" ? "Sign in" : "Create an account"}
        </h1>
        <p className="mt-1 text-sm muted">
          {mode === "in"
            ? "Access is role-gated. New accounts start as viewers."
            : "New accounts receive the viewer role and nothing else. Elevation is an explicit administrative action, never a side effect of registering."}
        </p>

        <form className="mt-4 space-y-3" onSubmit={submit}>
          {mode === "up" ? (
            <div>
              <label className="label" htmlFor="auth-name">Display name</label>
              <input
                id="auth-name"
                className="field mt-1"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                required
              />
            </div>
          ) : null}
          <div>
            <label className="label" htmlFor="auth-email">Email</label>
            <input
              id="auth-email"
              type="email"
              autoComplete="email"
              className="field mt-1"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="label" htmlFor="auth-password">Password</label>
            <input
              id="auth-password"
              type="password"
              autoComplete={mode === "in" ? "current-password" : "new-password"}
              className="field mt-1"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          {error ? (
            <p role="alert" className="rounded border border-alert-500/40 bg-alert-500/5 px-3 py-2 text-sm">
              {error}
            </p>
          ) : null}

          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy ? "Working…" : mode === "in" ? "Sign in" : "Create account"}
          </button>
        </form>

        <button
          type="button"
          className="mt-3 text-sm underline muted"
          onClick={() => {
            setMode(mode === "in" ? "up" : "in");
            setError(null);
          }}
        >
          {mode === "in" ? "Create an account instead" : "I already have an account"}
        </button>
      </div>

      {cloudIsLocal ? (
        <Callout tone="uncertainty" title="No cloud project is configured">
          <p>
            Authentication, reviews, scenarios and the audit log are stored in this browser only.
            None of the database policies in <code>supabase/migrations</code> are in force, so this
            mode demonstrates the workflow — it does not secure it.
          </p>
          <p className="mt-2">Demo accounts, password <code>demo</code>:</p>
          <ul className="mt-1 font-mono text-2xs">
            <li>admin@demo.invalid — administrator</li>
            <li>analyst@demo.invalid — analyst</li>
            <li>reviewer@demo.invalid — reviewer</li>
            <li>peer@demo.invalid — reviewer (the second opinion)</li>
          </ul>
        </Callout>
      ) : null}
    </div>
  );
}
