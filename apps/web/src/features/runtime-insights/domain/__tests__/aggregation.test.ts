import { describe, expect, it } from "vitest";

import { buildRuntimeSessionReport } from "../aggregation";
import { scoreRuntimeHealth } from "../scoring";
import { buildRuntimeInsightFixtureFlat } from "../../fixtures/runtime-insight-fixtures";

describe("runtime insight aggregation", () => {
  it("builds report with expected counts", () => {
    const events = buildRuntimeInsightFixtureFlat();
    const report = buildRuntimeSessionReport(events);

    expect(report.eventCount).toBeGreaterThan(20);
    expect(report.latency.p90Ms).toBeGreaterThan(0);
    expect(report.phaseSummary.length).toBeGreaterThan(0);
  });

  it("detects anomalies on slow sessions", () => {
    const events = buildRuntimeInsightFixtureFlat();
    const report = buildRuntimeSessionReport(events);

    expect(report.anomalies.length).toBeGreaterThan(0);
    expect(report.anomalies.some((item) => item.id === "latency-tail")).toBe(true);
  });

  it("scores runtime health within bounds", () => {
    const events = buildRuntimeInsightFixtureFlat();
    const report = buildRuntimeSessionReport(events);
    const score = scoreRuntimeHealth(report);

    expect(score.overall).toBeGreaterThanOrEqual(0);
    expect(score.overall).toBeLessThanOrEqual(1);
    expect(typeof score.summary).toBe("string");
  });
});
