import type { RuntimeHealthScore, RuntimeSessionReport } from "../domain";

type InsightSummaryCardsProps = {
  globalHealth: RuntimeHealthScore;
  reports: RuntimeSessionReport[];
  totalEvents: number;
  slowestSessionId: string | null;
  slowestSessionLatencyMs: number;
};

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function InsightSummaryCards({
  globalHealth,
  reports,
  totalEvents,
  slowestSessionId,
  slowestSessionLatencyMs,
}: InsightSummaryCardsProps) {
  const sessionCount = reports.length;
  const avgSuccessRate =
    reports.length === 0
      ? 0
      : reports.reduce((sum, report) => sum + report.successCount / Math.max(1, report.eventCount), 0) / reports.length;

  const avgFallbackRate =
    reports.length === 0
      ? 0
      : reports.reduce((sum, report) => sum + report.fallbackCount / Math.max(1, report.eventCount), 0) / reports.length;

  return (
    <section className="runtime-insight-grid" aria-label="Runtime insight summary">
      <article className="runtime-insight-card">
        <h3>Overall Runtime Health</h3>
        <p className="runtime-insight-value">{percent(globalHealth.overall)}</p>
        <p>{globalHealth.summary}</p>
      </article>

      <article className="runtime-insight-card">
        <h3>Coverage</h3>
        <p className="runtime-insight-value">{sessionCount} sessions</p>
        <p>{totalEvents} total trace events analyzed</p>
      </article>

      <article className="runtime-insight-card">
        <h3>Success Trend</h3>
        <p className="runtime-insight-value">{percent(avgSuccessRate)}</p>
        <p>Average done-event ratio across recent sessions</p>
      </article>

      <article className="runtime-insight-card">
        <h3>Fallback Pressure</h3>
        <p className="runtime-insight-value">{percent(avgFallbackRate)}</p>
        <p>
          {slowestSessionId
            ? `Slowest session ${slowestSessionId} at p90 ${slowestSessionLatencyMs}ms`
            : "No latency outlier yet"}
        </p>
      </article>
    </section>
  );
}
