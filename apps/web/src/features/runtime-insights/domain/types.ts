export type RuntimePhase = "planning" | "execution" | "waiting" | "synthesis" | "delivery";

export type RuntimeSeverity = "low" | "medium" | "high" | "critical";

export type RuntimeActorRole = "coordinator" | "researcher" | "synthesizer" | "tool" | "system";

export type RuntimeEventKind =
  | "thinking"
  | "tool_call"
  | "tool_result"
  | "waiting"
  | "retry"
  | "timeout"
  | "fallback"
  | "done"
  | "error";

export type RuntimeEventEnvelope = {
  id: string;
  sessionId: string;
  taskId?: string;
  nodeId?: string;
  branch?: string;
  phase: RuntimePhase;
  kind: RuntimeEventKind;
  actor: RuntimeActorRole;
  detail: string;
  at: string;
  durationMs?: number;
  attempts?: number;
  cacheHit?: boolean;
  provider?: string;
  sourceCount?: number;
  confidence?: number;
  fallbackUsed?: boolean;
  metadata?: Record<string, string | number | boolean | null | undefined>;
};

export type RuntimeLatencySummary = {
  totalMs: number;
  averageMs: number;
  p50Ms: number;
  p90Ms: number;
  p99Ms: number;
  maxMs: number;
};

export type RuntimePhaseSummary = {
  phase: RuntimePhase;
  count: number;
  failureCount: number;
  retryCount: number;
  fallbackCount: number;
  timeoutCount: number;
  avgDurationMs: number;
};

export type RuntimeProviderSummary = {
  provider: string;
  calls: number;
  failures: number;
  fallbackCount: number;
  avgConfidence: number;
};

export type RuntimeAnomaly = {
  id: string;
  severity: RuntimeSeverity;
  title: string;
  description: string;
  eventId?: string;
  recommendation?: string;
};

export type RuntimeSessionReport = {
  sessionId: string;
  generatedAt: string;
  eventCount: number;
  successCount: number;
  errorCount: number;
  waitingCount: number;
  retryCount: number;
  fallbackCount: number;
  cacheHitRate: number;
  confidenceScore: number;
  latency: RuntimeLatencySummary;
  phaseSummary: RuntimePhaseSummary[];
  providerSummary: RuntimeProviderSummary[];
  anomalies: RuntimeAnomaly[];
};

export type RuntimeTrendPoint = {
  label: string;
  successRate: number;
  avgLatencyMs: number;
  fallbackRate: number;
  eventCount: number;
};

export type RuntimeTrendReport = {
  generatedAt: string;
  points: RuntimeTrendPoint[];
};
