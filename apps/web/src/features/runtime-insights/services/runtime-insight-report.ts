import {
  buildRuntimeSessionReport,
  buildRuntimeTrendReport,
  normalizeRuntimeEvents,
  scoreRuntimeHealth,
  type RuntimeEventEnvelope,
  type RuntimeHealthScore,
  type RuntimeSessionReport,
  type RuntimeTrendReport,
} from "../domain";

export type RuntimeInsightSummary = {
  generatedAt: string;
  globalHealth: RuntimeHealthScore;
  reports: RuntimeSessionReport[];
  trend: RuntimeTrendReport;
};

export function buildRuntimeInsightSummary(
  eventsBySession: Record<string, RuntimeEventEnvelope[] | Record<string, unknown>[]>,
): RuntimeInsightSummary {
  const reports = Object.values(eventsBySession)
    .map((events) => normalizeRuntimeEvents(events as Record<string, unknown>[]))
    .map((events) => buildRuntimeSessionReport(events));

  const allEvents = reports
    .flatMap((report) => {
      const source = eventsBySession[report.sessionId] ?? [];
      return normalizeRuntimeEvents(source as Record<string, unknown>[]);
    })
    .sort((a, b) => Date.parse(a.at) - Date.parse(b.at));

  const globalReport = buildRuntimeSessionReport(allEvents);

  return {
    generatedAt: new Date().toISOString(),
    globalHealth: scoreRuntimeHealth(globalReport),
    reports: reports.sort((a, b) => b.eventCount - a.eventCount),
    trend: buildRuntimeTrendReport(reports),
  };
}
