import { describe, expect, it } from "vitest";

import { buildRuntimeInsightFixtureBySession } from "../fixtures/runtime-insight-fixtures";
import { buildRuntimeInsightSummary } from "./runtime-insight-report";

describe("runtime insight report service", () => {
  it("builds summary across sessions", () => {
    const fixture = buildRuntimeInsightFixtureBySession();
    const summary = buildRuntimeInsightSummary(fixture);

    expect(summary.reports.length).toBe(3);
    expect(summary.trend.points.length).toBe(3);
    expect(summary.globalHealth.overall).toBeGreaterThanOrEqual(0);
    expect(summary.globalHealth.overall).toBeLessThanOrEqual(1);
  });

  it("orders reports by event count descending", () => {
    const fixture = buildRuntimeInsightFixtureBySession();
    const summary = buildRuntimeInsightSummary(fixture);

    const eventCounts = summary.reports.map((report) => report.eventCount);
    const sorted = [...eventCounts].sort((a, b) => b - a);

    expect(eventCounts).toEqual(sorted);
  });
});
