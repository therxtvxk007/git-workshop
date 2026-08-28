import { NavLink } from "react-router-dom";
import clsx from "clsx";
import type { AppRole } from "@/lib/cloud";

/**
 * The ten sections, in the order an investigation actually runs: what is
 * ranked, then one district, then the evidence under it, then the human
 * judgement on top, then whether any of it has ever been right.
 */
export const NAV_SECTIONS: {
  to: string;
  label: string;
  hint: string;
  requires?: AppRole;
}[] = [
  { to: "/", label: "Overview", hint: "Ranked districts for the active cutoff" },
  { to: "/evidence", label: "Evidence", hint: "Search the observation ledger" },
  { to: "/review", label: "Review queue", hint: "Blinded annotation tasks", requires: "reviewer" },
  { to: "/backtests", label: "Backtests", hint: "Evaluation runs and comparison" },
  { to: "/data-health", label: "Data health", hint: "Coverage, delay and outages" },
  { to: "/models", label: "Models", hint: "Artefacts and run lineage" },
  { to: "/scenarios", label: "Scenarios", hint: "Hypothetical what-ifs", requires: "analyst" },
  { to: "/audit", label: "Audit", hint: "Append-only action timeline" },
  { to: "/admin", label: "Administration", hint: "Users, roles, disputes, exports", requires: "administrator" },
];

export function Sidebar({
  collapsed,
  onNavigate,
  can,
}: {
  collapsed: boolean;
  onNavigate?: () => void;
  can: (role: AppRole) => boolean;
}) {
  return (
    <nav aria-label="Sections" className="flex h-full flex-col gap-1 p-2">
      {NAV_SECTIONS.map((section) => {
        // A section the caller cannot use is shown disabled rather than hidden.
        // Hiding it makes the console look different for different people and
        // invites "it works on my screen" as an answer to a permission problem.
        const permitted = !section.requires || can(section.requires);
        if (!permitted) {
          return (
            <div
              key={section.to}
              className="flex cursor-not-allowed items-center gap-2 rounded-md px-3 py-2 text-sm opacity-45"
              title={`Requires the ${section.requires} role`}
            >
              <span aria-hidden>🔒</span>
              {!collapsed && <span className="truncate">{section.label}</span>}
            </div>
          );
        }
        return (
          <NavLink
            key={section.to}
            to={section.to}
            end={section.to === "/"}
            onClick={onNavigate}
            title={collapsed ? `${section.label} — ${section.hint}` : section.hint}
            className={({ isActive }) =>
              clsx(
                "rounded-md px-3 py-2 text-sm transition-colors",
                isActive
                  ? "bg-navy-600 text-white"
                  : "hover:bg-navy-100 dark:hover:bg-navy-800",
              )
            }
          >
            {collapsed ? (
              <span aria-hidden className="block text-center font-semibold">
                {section.label.slice(0, 2)}
              </span>
            ) : (
              <>
                <span className="block font-medium">{section.label}</span>
                <span className="block text-2xs opacity-70">{section.hint}</span>
              </>
            )}
            {collapsed && <span className="sr-only">{section.label}</span>}
          </NavLink>
        );
      })}
    </nav>
  );
}
