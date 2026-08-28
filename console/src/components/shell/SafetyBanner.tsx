import { apiMode } from "@/lib/api/client";
import type { SnapshotInfo } from "@/lib/api/types";

/**
 * The line this console must never stop saying.
 *
 * It is rendered in the shell, so it appears on every route, and it carries a
 * `print-only` twin so a printed or PDF-exported page cannot lose it. The
 * wording is different for synthetic and live data, but neither version claims
 * the output is fit for operational use, because neither is: calibration is
 * `identity@uncalibrated` and the alert policy is a placeholder threshold with
 * no miss-rate guarantee.
 */
export function SafetyBanner({ snapshot }: { snapshot: SnapshotInfo | undefined }) {
  const synthetic = apiMode.mode === "mock" || snapshot?.data_mode === "synthetic";

  return (
    <div
      className={`border-b px-4 py-2 text-sm ${
        synthetic
          ? "border-uncertainty-400/40 bg-uncertainty-400/10"
          : "border-navy-500/40 bg-navy-500/10"
      }`}
      role="note"
    >
      <p className="mx-auto max-w-[1600px]">
        <strong className="uppercase tracking-wide">
          {synthetic ? "Synthetic data — research use only" : "Research use only"}
        </strong>
        <span className="muted">
          {" "}
          {synthetic
            ? "Every value shown is generated demo data. No district, event, evidence item or outcome here is real."
            : "This console displays research output from the Pramaan-X engine."}{" "}
          It is not operational intelligence. Probabilities are not calibrated
          {snapshot ? ` (${snapshot.calibration})` : ""} and statuses come from a placeholder
          threshold policy{snapshot ? ` (${snapshot.alert_policy})` : ""} that carries no
          miss-rate guarantee. Do not use it to direct response, deployment or resource allocation.
        </span>
      </p>
    </div>
  );
}
