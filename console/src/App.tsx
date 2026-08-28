import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/AppShell";
import { useSession } from "@/components/SessionProvider";
import { DeniedState, LoadingState } from "@/components/states/StateViews";
import type { AppRole } from "@/lib/cloud";
import { Auth } from "@/routes/Auth";
import { Overview } from "@/routes/Overview";
import { ForecastDetailRoute } from "@/routes/ForecastDetail";
import { EvidenceExplorer } from "@/routes/EvidenceExplorer";
import { ReviewQueue } from "@/routes/ReviewQueue";
import { ReviewWorkspace } from "@/routes/ReviewWorkspace";
import { Backtests } from "@/routes/Backtests";
import { DataHealthRoute } from "@/routes/DataHealth";
import { Models } from "@/routes/Models";
import { Scenarios } from "@/routes/Scenarios";
import { ScenarioWorkspace } from "@/routes/ScenarioWorkspace";
import { AuditTimeline } from "@/routes/Audit";
import { Admin } from "@/routes/Admin";

/**
 * Route gating.
 *
 * This is navigation, not authorisation. Every protected action is refused
 * again by an RLS policy, and the two are deliberately independent: if this
 * component had a bug tomorrow the database would still say no.
 */
function Protected({ children, role }: { children: ReactNode; role?: AppRole }) {
  const { user, loading, can } = useSession();
  const location = useLocation();

  if (loading) return <LoadingState label="Checking your session" />;
  if (!user) return <Navigate to="/auth" replace state={{ from: location.pathname + location.search }} />;
  if (role && !can(role)) {
    return (
      <DeniedState>
        <p>
          This section requires the <strong>{role}</strong> role. You currently hold:{" "}
          <strong>{user.roles.join(", ") || "no role"}</strong>.
        </p>
        <p className="mt-2">
          An administrator can grant it. Nothing is hidden from you by this screen that the database
          would otherwise have returned.
        </p>
      </DeniedState>
    );
  }
  return <>{children}</>;
}

export function App() {
  return (
    <Routes>
      <Route path="/auth" element={<Auth />} />
      <Route element={<AppShell />}>
        <Route index element={<Protected><Overview /></Protected>} />
        <Route path="/forecasts/:forecastId" element={<Protected><ForecastDetailRoute /></Protected>} />
        <Route path="/evidence" element={<Protected><EvidenceExplorer /></Protected>} />
        <Route path="/review" element={<Protected role="reviewer"><ReviewQueue /></Protected>} />
        <Route path="/review/:taskId" element={<Protected role="reviewer"><ReviewWorkspace /></Protected>} />
        <Route path="/backtests" element={<Protected><Backtests /></Protected>} />
        <Route path="/data-health" element={<Protected><DataHealthRoute /></Protected>} />
        <Route path="/models" element={<Protected><Models /></Protected>} />
        <Route path="/scenarios" element={<Protected role="analyst"><Scenarios /></Protected>} />
        <Route path="/scenarios/:sessionId" element={<Protected role="analyst"><ScenarioWorkspace /></Protected>} />
        <Route path="/audit" element={<Protected><AuditTimeline /></Protected>} />
        <Route path="/admin" element={<Protected role="administrator"><Admin /></Protected>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
