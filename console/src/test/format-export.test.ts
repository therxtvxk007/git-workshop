import { describe, expect, it } from "vitest";
import {
  formatInterval,
  formatProbability,
  formatProbabilityDelta,
  formatRelativeToCutoff,
  formatUtc,
  probabilityColor,
} from "@/lib/format";
import { exportFilename, toCsv, toJson, type ExportContext } from "@/lib/export";

describe("formatting", () => {
  it("28. does not imply precision the model does not have", () => {
    // 0.6231 rendered as "62.31%" claims four significant figures from a model
    // whose calibration is recorded as identity@uncalibrated.
    expect(formatProbability(0.6231)).toBe("62%");
    expect(formatProbability(0.043)).toBe("4.3%");
    // The branch threshold has to agree with the rounding, or 9.99% and 10%
    // render at two different precisions.
    expect(formatProbability(0.0999)).toBe("10%");
    expect(formatProbability(0.0994)).toBe("9.9%");
  });

  it("29. never renders a non-zero probability as 0% or a non-one as 100%", () => {
    expect(formatProbability(0.0004)).toBe("<0.1%");
    expect(formatProbability(0.9997)).toBe(">99.9%");
    expect(formatProbability(0)).toBe("0%");
    expect(formatProbability(1)).toBe("100%");
  });

  it("30. renders a missing probability as an em dash, not as zero", () => {
    expect(formatProbability(null)).toBe("—");
    expect(formatProbability(undefined)).toBe("—");
    expect(formatProbability(Number.NaN)).toBe("—");
  });

  it("31. never abbreviates an interval to one bound", () => {
    expect(formatInterval({ lower: 0.2, upper: 0.5, coverage: 0.9, method: "m" })).toBe("20% – 50%");
    expect(formatInterval(null)).toBe("no interval");
  });

  it("32. always states the timezone", () => {
    const rendered = formatUtc("2026-01-15T00:00:00Z");
    expect(rendered).toBe("2026-01-15 00:00 UTC");
    // Same instant, different offset in the string: the rendering must not move.
    expect(formatUtc("2026-01-15T05:30:00+05:30")).toBe(rendered);
  });

  it("33. describes evidence timing relative to the cutoff, with direction", () => {
    const cutoff = "2026-01-15T00:00:00Z";
    expect(formatRelativeToCutoff("2026-01-13T00:00:00Z", cutoff)).toBe("2 d before cutoff");
    expect(formatRelativeToCutoff("2026-01-15T06:00:00Z", cutoff)).toBe("6 h after cutoff");
  });

  it("34. signs probability deltas", () => {
    expect(formatProbabilityDelta(0.12)).toBe("+12 pp");
    expect(formatProbabilityDelta(-0.043)).toBe("−4.3 pp");
  });

  it("35. keeps the probability ramp monotonic and bounded", () => {
    const colours = [0, 0.25, 0.5, 0.75, 1].map(probabilityColor);
    expect(new Set(colours).size).toBe(5);
    expect(probabilityColor(-5)).toBe(probabilityColor(0));
    expect(probabilityColor(5)).toBe(probabilityColor(1));
  });
});

const CONTEXT: ExportContext = {
  name: "ranked-districts",
  cutoffAt: "2026-01-15T00:00:00Z",
  snapshotHash: "sha256:deadbeef",
  dataMode: "synthetic",
  filters: { event_family: "flood" },
};

describe("export", () => {
  const rows = [{ district: "Patna", probability: 0.42 }];
  const columns = [
    { key: "district" as const, header: "district" },
    { key: "probability" as const, header: "probability" },
  ];

  it("36. puts the cutoff, snapshot and research-use notice inside the CSV", () => {
    // A CSV that leaves this console loses every piece of surrounding context,
    // so the context travels in the file.
    const csv = toCsv(rows, columns, CONTEXT);
    expect(csv).toContain("Cutoff: 2026-01-15 00:00 UTC");
    expect(csv).toContain("Snapshot: sha256:deadbeef");
    expect(csv).toContain("RESEARCH USE ONLY");
    expect(csv).toContain("SYNTHETIC DATA");
    expect(csv).toContain('Filters: {"event_family":"flood"}');
  });

  it("37. neutralises spreadsheet formula injection", () => {
    const csv = toCsv(
      [{ district: "=1+1", probability: 0.1 }],
      columns,
      CONTEXT,
    );
    // An export that runs code when opened is not an acceptable way to share
    // a district table.
    expect(csv).toContain("'=1+1");
    expect(csv).not.toMatch(/^=1\+1/m);
  });

  it("38. quotes cells containing separators", () => {
    const csv = toCsv([{ district: 'Pat"na, Bihar', probability: 0.1 }], columns, CONTEXT);
    expect(csv).toContain('"Pat""na, Bihar"');
  });

  it("39. marks demo and hypothetical status in JSON", () => {
    const json = JSON.parse(toJson(rows, { ...CONTEXT, hypothetical: true }));
    expect(json.export.is_demo).toBe(true);
    expect(json.export.is_hypothetical).toBe(true);
    expect(json.export.notice.join(" ")).toContain("HYPOTHETICAL");
    expect(json.row_count).toBe(1);
  });

  it("40. watermarks the filename", () => {
    expect(exportFilename(CONTEXT, "csv")).toBe("DEMO-pramaanx-ranked-districts-2026-01-15.csv");
    expect(exportFilename({ ...CONTEXT, hypothetical: true }, "json")).toBe(
      "DEMO-HYPOTHETICAL-pramaanx-ranked-districts-2026-01-15.json",
    );
    expect(exportFilename({ ...CONTEXT, dataMode: "live" }, "csv")).toBe(
      "pramaanx-ranked-districts-2026-01-15.csv",
    );
  });
});
