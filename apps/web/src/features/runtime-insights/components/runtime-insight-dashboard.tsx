"use client";

import type { RuntimeEventEnvelope } from "../domain";
import { InsightAnomalyList } from "./insight-anomaly-list";
import { InsightPhaseTable } from "./insight-phase-table";
import { InsightSummaryCards } from "./insight-summary-cards";
import { useRuntimeInsightModel } from "../hooks/use-runtime-insight-model";

type RuntimeInsightDashboardProps = {
  eventsBySession: Record<string, RuntimeEventEnvelope[] | Record<string, unknown>[]>;
};

export function RuntimeInsightDashboard({ eventsBySession }: RuntimeInsightDashboardProps) {
  const model = useRuntimeInsightModel({ sessions: eventsBySession as Record<string, Record<string, unknown>[]> });

  return (
    <section className="runtime-insight-dashboard">
      <header className="runtime-insight-header">
        <p className="runtime-insight-kicker">Runtime Insights</p>
        <h2>Session reliability and latency intelligence</h2>
        <p>
          This dashboard summarizes runtime behavior from trace events, highlighting slow sessions, fallback pressure,
          and operational anomalies.
        </p>
      </header>

      <InsightSummaryCards
        globalHealth={model.globalHealth}
        reports={model.reports}
        totalEvents={model.totalEvents}
        slowestSessionId={model.slowestSessionId}
        slowestSessionLatencyMs={model.slowestSessionLatencyMs}
      />

      <div className="runtime-insight-layout">
        <InsightPhaseTable reports={model.reports} />
        <InsightAnomalyList reports={model.reports} />
      </div>
    </section>
  );
}
