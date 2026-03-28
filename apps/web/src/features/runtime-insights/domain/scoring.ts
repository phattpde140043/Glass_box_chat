import type { RuntimeAnomaly, RuntimeSessionReport } from "./types";

const SEVERITY_WEIGHT: Record<RuntimeAnomaly["severity"], number> = {
  low: 0.03,
  medium: 0.08,
  high: 0.16,
  critical: 0.3,
};

function clamp(value: number, min = 0, max = 1): number {
  return Math.min(max, Math.max(min, value));
}

export type RuntimeHealthScore = {
  reliability: number;
  efficiency: number;
  quality: number;
  risk: number;
  overall: number;
  summary: string;
};

function anomalyPenalty(anomalies: RuntimeAnomaly[]): number {
  return anomalies.reduce((sum, anomaly) => sum + (SEVERITY_WEIGHT[anomaly.severity] ?? 0), 0);
}

function reliabilityScore(report: RuntimeSessionReport): number {
  const successRatio = report.successCount / Math.max(1, report.eventCount);
  const errorRatio = report.errorCount / Math.max(1, report.eventCount);
  const timeoutRatio = report.phaseSummary.reduce((sum, phase) => sum + phase.timeoutCount, 0) / Math.max(1, report.eventCount);

  return clamp(successRatio * 0.7 + (1 - errorRatio) * 0.2 + (1 - timeoutRatio) * 0.1);
}

function efficiencyScore(report: RuntimeSessionReport): number {
  const latencyScore = 1 - clamp(report.latency.p90Ms / 12000);
  const retryScore = 1 - clamp(report.retryCount / Math.max(1, report.eventCount));
  const fallbackScore = 1 - clamp(report.fallbackCount / Math.max(1, report.eventCount));

  return clamp(latencyScore * 0.55 + retryScore * 0.25 + fallbackScore * 0.2);
}

function qualityScore(report: RuntimeSessionReport): number {
  const confidence = clamp(report.confidenceScore);
  const cacheValue = clamp(report.cacheHitRate);

  return clamp(confidence * 0.75 + cacheValue * 0.25);
}

function riskScore(report: RuntimeSessionReport): number {
  const anomalyRisk = clamp(anomalyPenalty(report.anomalies));
  const errorRisk = clamp(report.errorCount / Math.max(1, report.eventCount));
  const tailLatencyRisk = clamp(report.latency.p99Ms / 18000);

  return clamp(anomalyRisk * 0.5 + errorRisk * 0.35 + tailLatencyRisk * 0.15);
}

function summaryFromOverall(overall: number): string {
  if (overall >= 0.85) {
    return "Runtime health is strong with consistent execution quality.";
  }
  if (overall >= 0.65) {
    return "Runtime health is acceptable, but there are optimization opportunities.";
  }
  if (overall >= 0.4) {
    return "Runtime health is degraded and requires targeted reliability work.";
  }
  return "Runtime health is at risk; immediate stabilization is recommended.";
}

export function scoreRuntimeHealth(report: RuntimeSessionReport): RuntimeHealthScore {
  const reliability = reliabilityScore(report);
  const efficiency = efficiencyScore(report);
  const quality = qualityScore(report);
  const risk = riskScore(report);

  const overall = clamp(reliability * 0.38 + efficiency * 0.27 + quality * 0.25 + (1 - risk) * 0.1);

  return {
    reliability: Number(reliability.toFixed(3)),
    efficiency: Number(efficiency.toFixed(3)),
    quality: Number(quality.toFixed(3)),
    risk: Number(risk.toFixed(3)),
    overall: Number(overall.toFixed(3)),
    summary: summaryFromOverall(overall),
  };
}
