import type { RuntimeAnomaly, RuntimeSessionReport } from "../domain";

type InsightAnomalyListProps = {
  reports: RuntimeSessionReport[];
};

function severityLabel(anomaly: RuntimeAnomaly): string {
  if (anomaly.severity === "critical") {
    return "Critical";
  }
  if (anomaly.severity === "high") {
    return "High";
  }
  if (anomaly.severity === "medium") {
    return "Medium";
  }
  return "Low";
}

function aggregateAnomalies(reports: RuntimeSessionReport[]): Array<{ sessionId: string; anomaly: RuntimeAnomaly }> {
  return reports.flatMap((report) => report.anomalies.map((anomaly) => ({ sessionId: report.sessionId, anomaly })));
}

export function InsightAnomalyList({ reports }: InsightAnomalyListProps) {
  const anomalies = aggregateAnomalies(reports);

  return (
    <section className="runtime-insight-panel" aria-label="Anomaly list">
      <div className="runtime-insight-panel-header">
        <h3>Anomalies & Recommendations</h3>
        <p>Focused reliability issues extracted from trace patterns.</p>
      </div>

      {anomalies.length === 0 ? (
        <p className="runtime-insight-empty">No anomalies detected in current session set.</p>
      ) : (
        <ul className="runtime-insight-anomaly-list">
          {anomalies.map(({ sessionId, anomaly }) => (
            <li key={`${sessionId}-${anomaly.id}`} className={`runtime-insight-anomaly ${anomaly.severity}`}>
              <div className="runtime-insight-anomaly-head">
                <span className="runtime-insight-badge">{severityLabel(anomaly)}</span>
                <strong>{anomaly.title}</strong>
                <span className="runtime-insight-session">{sessionId}</span>
              </div>
              <p>{anomaly.description}</p>
              {anomaly.recommendation ? <p className="runtime-insight-reco">{anomaly.recommendation}</p> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
