import { useEffect, useState } from "react";
import { Outlet, useSearchParams } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { SafetyBanner } from "./SafetyBanner";
import { useSnapshot } from "@/lib/queries";
import { useSession } from "@/components/SessionProvider";
import { ErrorBoundary } from "@/components/states/ErrorBoundary";
import { UnavailableState } from "@/components/states/StateViews";

export function AppShell() {
  const { data: snapshot, error } = useSnapshot();
  const { can } = useSession();
  const [params] = useSearchParams();
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-navy-600 focus:px-3 focus:py-2 focus:text-white"
      >
        Skip to content
      </a>

      <TopBar
        snapshot={snapshot}
        eventFamily={params.get("family")}
        dark={dark}
        onToggleTheme={() => setDark((d) => !d)}
        onToggleSidebar={() => {
          // One control, two behaviours: it collapses the rail on a desktop and
          // opens the drawer on a phone, so there is nothing extra to learn.
          if (window.matchMedia("(min-width: 1024px)").matches) setCollapsed((c) => !c);
          else setDrawerOpen((o) => !o);
        }}
      />

      <SafetyBanner snapshot={snapshot} />

      <div className="flex">
        <aside
          className={`hidden shrink-0 border-r border-[rgb(var(--border))] lg:block no-print ${
            collapsed ? "w-16" : "w-60"
          }`}
        >
          <div className="sticky top-[3.25rem]">
            <Sidebar collapsed={collapsed} can={can} />
          </div>
        </aside>

        {drawerOpen ? (
          <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
            <button
              type="button"
              aria-label="Close navigation"
              className="absolute inset-0 bg-black/50"
              onClick={() => setDrawerOpen(false)}
            />
            <div className="relative z-10 h-full w-64 border-r border-[rgb(var(--border))] bg-[rgb(var(--surface-raised))]">
              <Sidebar collapsed={false} can={can} onNavigate={() => setDrawerOpen(false)} />
            </div>
          </div>
        ) : null}

        <main id="main" className="min-w-0 flex-1 p-4">
          {error ? (
            <div className="mb-4">
              <UnavailableState error={error}>
                The snapshot metadata could not be loaded, so the cutoff and snapshot hash shown
                above are unknown. Every figure on this page should be treated as unattributable
                until that resolves.
              </UnavailableState>
            </div>
          ) : null}
          <ErrorBoundary label="This page">
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
