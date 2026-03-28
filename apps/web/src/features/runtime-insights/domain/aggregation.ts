import type {
  RuntimeAnomaly,
  RuntimeEventEnvelope,
  RuntimeLatencySummary,
  RuntimePhase,
  RuntimePhaseSummary,
  RuntimeProviderSummary,
  RuntimeSessionReport,
  RuntimeSeverity,
  RuntimeTrendPoint,
  RuntimeTrendReport,
} from "./types";

function percentile(sortedValues: number[], rank: number): number {
  if (sortedValues.length === 0) {
    return 0;
  }
  const p = Math.max(0, Math.min(1, rank));
  const index = Math.min(sortedValues.length - 1, Math.floor(p * sortedValues.length));
  return sortedValues[index] ?? 0;
}

function buildLatencySummary(events: RuntimeEventEnvelope[]): RuntimeLatencySummary {
  const durations = events
    .map((event) => event.durationMs ?? 0)
    .filter((value) => Number.isFinite(value) && value >= 0)
    .sort((a, b) => a - b);

  if (durations.length === 0) {
    return {
      totalMs: 0,
      averageMs: 0,
      p50Ms: 0,
      p90Ms: 0,
      p99Ms: 0,
      maxMs: 0,
    };
  }

  const totalMs = durations.reduce((sum, value) => sum + value, 0);
  return {
    totalMs,
    averageMs: Math.round(totalMs / durations.length),
    p50Ms: Math.round(percentile(durations, 0.5)),
    p90Ms: Math.round(percentile(durations, 0.9)),
    p99Ms: Math.round(percentile(durations, 0.99)),
    maxMs: durations[durations.length - 1] ?? 0,
  };
}

function phaseTemplate(phase: RuntimePhase): RuntimePhaseSummary {
  return {
    phase,
    count: 0,
    failureCount: 0,
    retryCount: 0,
    fallbackCount: 0,
    timeoutCount: 0,
    avgDurationMs: 0,
  };
}

function summarizeByPhase(events: RuntimeEventEnvelope[]): RuntimePhaseSummary[] {
  const map = new Map<RuntimePhase, RuntimePhaseSummary>();
  const durationByPhase = new Map<RuntimePhase, number[]>();

  for (const event of events) {
    const bucket = map.get(event.phase) ?? phaseTemplate(event.phase);
    bucket.count += 1;

    if (event.kind === "error") {
      bucket.failureCount += 1;
    }
    if ((event.attempts ?? 0) > 1 || event.kind === "retry") {
      bucket.retryCount += 1;
    }
    if (event.fallbackUsed || event.kind === "fallback") {
      bucket.fallbackCount += 1;
    }
    if (event.kind === "timeout") {
      bucket.timeoutCount += 1;
    }

    map.set(event.phase, bucket);

    if (typeof event.durationMs === "number" && event.durationMs >= 0) {
      const durations = durationByPhase.get(event.phase) ?? [];
      durations.push(event.durationMs);
      durationByPhase.set(event.phase, durations);
    }
  }

  const orderedPhases: RuntimePhase[] = ["planning", "execution", "waiting", "synthesis", "delivery"];

  return orderedPhases
    .map((phase) => {
      const summary = map.get(phase) ?? phaseTemplate(phase);
      const durations = durationByPhase.get(phase) ?? [];
      summary.avgDurationMs = durations.length === 0 ? 0 : Math.round(durations.reduce((a, b) => a + b, 0) / durations.length);
      return summary;
    })
    .filter((summary) => summary.count > 0);
}

function summarizeProviders(events: RuntimeEventEnvelope[]): RuntimeProviderSummary[] {
  const map = new Map<string, RuntimeProviderSummary>();

  for (const event of events) {
    const providerName = (event.provider ?? "unknown").trim() || "unknown";
    const bucket =
      map.get(providerName) ?? {
        provider: providerName,
        calls: 0,
        failures: 0,
        fallbackCount: 0,
        avgConfidence: 0,
      };

    if (event.kind === "tool_call" || event.kind === "tool_result" || event.kind === "fallback" || event.kind === "error") {
      bucket.calls += 1;
    }
    if (event.kind === "error") {
      bucket.failures += 1;
    }
    if (event.fallbackUsed || event.kind === "fallback") {
      bucket.fallbackCount += 1;
    }

    if (typeof event.confidence === "number" && event.confidence > 0) {
      const historicalTotal = bucket.avgConfidence * Math.max(0, bucket.calls - 1);
      bucket.avgConfidence = Number(((historicalTotal + event.confidence) / bucket.calls).toFixed(3));
    }

    map.set(providerName, bucket);
  }

  return [...map.values()].sort((a, b) => b.calls - a.calls);
}

function anomaly(id: string, severity: RuntimeSeverity, title: string, description: string, recommendation: string, eventId?: string): RuntimeAnomaly {
  return { id, severity, title, description, recommendation, eventId };
}

function detectAnomalies(events: RuntimeEventEnvelope[], latency: RuntimeLatencySummary): RuntimeAnomaly[] {
  const anomalies: RuntimeAnomaly[] = [];

  const timeoutEvents = events.filter((event) => event.kind === "timeout");
  if (timeoutEvents.length >= 2) {
    anomalies.push(
      anomaly(
        "timeout-burst",
        timeoutEvents.length >= 4 ? "critical" : "high",
        "Timeout burst detected",
        `Detected ${timeoutEvents.length} timeout events in this session.`,
        "Increase provider timeout and add provider-specific fallback routing.",
        timeoutEvents[0]?.id,
      ),
    );
  }

  const retryEvents = events.filter((event) => (event.attempts ?? 1) > 1 || event.kind === "retry");
  if (retryEvents.length >= 3) {
    anomalies.push(
      anomaly(
        "retry-spike",
        retryEvents.length >= 6 ? "high" : "medium",
        "Retry spike",
        `Observed ${retryEvents.length} retry-related events.`,
        "Inspect transient error categories and adjust exponential backoff settings.",
        retryEvents[0]?.id,
      ),
    );
  }

  if (latency.p90Ms > 7000 || latency.p99Ms > 12000) {
    anomalies.push(
      anomaly(
        "latency-tail",
        latency.p99Ms > 15000 ? "critical" : "high",
        "High latency tail",
        `Latency tail is elevated (p90=${latency.p90Ms}ms, p99=${latency.p99Ms}ms).`,
        "Limit expensive tool fan-out and review slowest nodes for caching opportunities.",
      ),
    );
  }

  const fallbackEvents = events.filter((event) => event.fallbackUsed || event.kind === "fallback");
  if (fallbackEvents.length > 0 && fallbackEvents.length / Math.max(1, events.length) > 0.2) {
    anomalies.push(
      anomaly(
        "fallback-rate",
        "medium",
        "Fallback rate is elevated",
        `${Math.round((fallbackEvents.length / Math.max(1, events.length)) * 100)}% events used fallback path.`,
        "Tune semantic routing threshold and ensure primary providers are healthy.",
        fallbackEvents[0]?.id,
      ),
    );
  }

  return anomalies;
}

export function buildRuntimeSessionReport(events: RuntimeEventEnvelope[]): RuntimeSessionReport {
  const ordered = [...events].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const sessionId = ordered[0]?.sessionId ?? "session-unknown";

  const successCount = ordered.filter((event) => event.kind === "done").length;
  const errorCount = ordered.filter((event) => event.kind === "error").length;
  const waitingCount = ordered.filter((event) => event.kind === "waiting").length;
  const retryCount = ordered.filter((event) => (event.attempts ?? 1) > 1 || event.kind === "retry").length;
  const fallbackCount = ordered.filter((event) => event.fallbackUsed || event.kind === "fallback").length;
  const cacheHits = ordered.filter((event) => event.cacheHit).length;
  const cacheHitRate = Number((cacheHits / Math.max(1, ordered.length)).toFixed(3));

  const confidenceValues = ordered
    .map((event) => event.confidence)
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  const confidenceScore =
    confidenceValues.length === 0
      ? 0
      : Number((confidenceValues.reduce((sum, value) => sum + value, 0) / confidenceValues.length).toFixed(3));

  const latency = buildLatencySummary(ordered);
  const phaseSummary = summarizeByPhase(ordered);
  const providerSummary = summarizeProviders(ordered);
  const anomalies = detectAnomalies(ordered, latency);

  return {
    sessionId,
    generatedAt: new Date().toISOString(),
    eventCount: ordered.length,
    successCount,
    errorCount,
    waitingCount,
    retryCount,
    fallbackCount,
    cacheHitRate,
    confidenceScore,
    latency,
    phaseSummary,
    providerSummary,
    anomalies,
  };
}

export function buildRuntimeTrendReport(reports: RuntimeSessionReport[]): RuntimeTrendReport {
  const points: RuntimeTrendPoint[] = reports.map((report) => {
    const successRate = Number((report.successCount / Math.max(1, report.eventCount)).toFixed(3));
    const fallbackRate = Number((report.fallbackCount / Math.max(1, report.eventCount)).toFixed(3));

    return {
      label: report.sessionId,
      successRate,
      avgLatencyMs: report.latency.averageMs,
      fallbackRate,
      eventCount: report.eventCount,
    };
  });

  return {
    generatedAt: new Date().toISOString(),
    points,
  };
}
