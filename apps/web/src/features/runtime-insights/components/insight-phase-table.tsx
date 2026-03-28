import type { RuntimeSessionReport } from "../domain";

type InsightPhaseTableProps = {
  reports: RuntimeSessionReport[];
};

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function InsightPhaseTable({ reports }: InsightPhaseTableProps) {
  return (
    <section className="runtime-insight-panel" aria-label="Session table">
      <div className="runtime-insight-panel-header">
        <h3>Session Diagnostics</h3>
        <p>Latency and reliability snapshots per session.</p>
      </div>

      <div className="runtime-insight-table-wrap">
        <table className="runtime-insight-table">
          <thead>
            <tr>
              <th>Session</th>
              <th>Events</th>
              <th>Success</th>
              <th>Error</th>
              <th>Fallback</th>
              <th>Cache Hit</th>
              <th>P90</th>
              <th>P99</th>
            </tr>
          </thead>

          <tbody>
            {reports.map((report) => {
              const successRate = report.successCount / Math.max(1, report.eventCount);
              return (
                <tr key={report.sessionId}>
                  <td>{report.sessionId}</td>
                  <td>{report.eventCount}</td>
                  <td>{formatPercent(successRate)}</td>
                  <td>{report.errorCount}</td>
                  <td>{report.fallbackCount}</td>
                  <td>{formatPercent(report.cacheHitRate)}</td>
                  <td>{report.latency.p90Ms}ms</td>
                  <td>{report.latency.p99Ms}ms</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
