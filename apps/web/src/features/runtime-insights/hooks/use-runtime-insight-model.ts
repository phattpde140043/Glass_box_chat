"use client";

import { useMemo } from "react";
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

type UseRuntimeInsightModelInput = {
  sessions: Record<string, Record<string, unknown>[]>;
};

export type RuntimeInsightViewModel = {
  reports: RuntimeSessionReport[];
  trend: RuntimeTrendReport;
  globalHealth: RuntimeHealthScore;
  totalEvents: number;
  slowestSessionId: string | null;
  slowestSessionLatencyMs: number;
};

function emptyHealth(): RuntimeHealthScore {
  return {
    reliability: 0,
    efficiency: 0,
    quality: 0,
    risk: 1,
    overall: 0,
    summary: "No session data yet.",
  };
}

function mergeAllEvents(sessions: Record<string, RuntimeEventEnvelope[]>): RuntimeEventEnvelope[] {
  const all = Object.values(sessions).flat();
  return all.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
}

function findSlowestSession(reports: RuntimeSessionReport[]): { id: string | null; latency: number } {
  if (reports.length === 0) {
    return { id: null, latency: 0 };
  }

  const slowest = reports.reduce((current, candidate) =>
    candidate.latency.p90Ms > current.latency.p90Ms ? candidate : current,
  );

  return {
    id: slowest.sessionId,
    latency: slowest.latency.p90Ms,
  };
}

export function useRuntimeInsightModel({ sessions }: UseRuntimeInsightModelInput): RuntimeInsightViewModel {
  return useMemo(() => {
    const normalizedBySession: Record<string, RuntimeEventEnvelope[]> = Object.fromEntries(
      Object.entries(sessions).map(([sessionId, rawEvents]) => [sessionId, normalizeRuntimeEvents(rawEvents)]),
    );

    const reports = Object.values(normalizedBySession)
      .map((events) => buildRuntimeSessionReport(events))
      .sort((a, b) => b.eventCount - a.eventCount);

    const allEvents = mergeAllEvents(normalizedBySession);
    const syntheticGlobalReport = buildRuntimeSessionReport(allEvents);
    const globalHealth = allEvents.length === 0 ? emptyHealth() : scoreRuntimeHealth(syntheticGlobalReport);
    const trend = buildRuntimeTrendReport(reports);

    const slowest = findSlowestSession(reports);

    return {
      reports,
      trend,
      globalHealth,
      totalEvents: allEvents.length,
      slowestSessionId: slowest.id,
      slowestSessionLatencyMs: slowest.latency,
    };
  }, [sessions]);
}
