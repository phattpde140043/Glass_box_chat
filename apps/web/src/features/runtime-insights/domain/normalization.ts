import type { RuntimeActorRole, RuntimeEventEnvelope, RuntimeEventKind, RuntimePhase } from "./types";

type RawEvent = Record<string, unknown>;

const PHASE_MAP: Record<string, RuntimePhase> = {
  thinking: "planning",
  tool_call: "execution",
  tool_result: "execution",
  waiting: "waiting",
  retry: "execution",
  timeout: "execution",
  fallback: "execution",
  done: "delivery",
  error: "delivery",
};

const ACTOR_MAP: Record<string, RuntimeActorRole> = {
  OrchestratorAgent: "coordinator",
  PlannerAgent: "coordinator",
  AnswerSkillAgent: "synthesizer",
  SearchSkill: "researcher",
  CoordinatorAgent: "coordinator",
  AgentSummarizer: "synthesizer",
};

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function normalizeKind(kind: string): RuntimeEventKind {
  const k = kind.trim();
  if (
    k === "thinking" ||
    k === "tool_call" ||
    k === "tool_result" ||
    k === "waiting" ||
    k === "retry" ||
    k === "timeout" ||
    k === "fallback" ||
    k === "done" ||
    k === "error"
  ) {
    return k;
  }
  return "thinking";
}

function normalizePhase(kind: RuntimeEventKind, rawPhase: string): RuntimePhase {
  const clean = rawPhase.trim();
  if (clean === "planning" || clean === "execution" || clean === "waiting" || clean === "synthesis" || clean === "delivery") {
    return clean;
  }
  return PHASE_MAP[kind] ?? "execution";
}

function normalizeActor(raw: string): RuntimeActorRole {
  if (raw === "coordinator" || raw === "researcher" || raw === "synthesizer" || raw === "tool" || raw === "system") {
    return raw;
  }
  return ACTOR_MAP[raw] ?? "system";
}

export function normalizeRuntimeEvent(raw: RawEvent, index: number): RuntimeEventEnvelope {
  const kind = normalizeKind(asString(raw.event, asString(raw.kind, "thinking")));
  const actor = normalizeActor(asString(raw.agent, asString(raw.actor, "system")));

  return {
    id: asString(raw.id, `evt-${index + 1}`),
    sessionId: asString(raw.sessionId, asString(raw.session_id, "session-unknown")),
    taskId: asString(raw.taskId, asString(raw.task_id, "")) || undefined,
    nodeId: asString(raw.nodeId, asString(raw.node_id, "")) || undefined,
    branch: asString(raw.branch, "") || undefined,
    phase: normalizePhase(kind, asString(raw.phase)),
    kind,
    actor,
    detail: asString(raw.detail, ""),
    at: asString(raw.at, new Date().toISOString()),
    durationMs: asNumber(raw.durationMs, asNumber(raw.duration_ms, 0)) || undefined,
    attempts: asNumber(raw.attempts, 0) || undefined,
    cacheHit: asBoolean(raw.cacheHit, asBoolean(raw.cache_hit, false)),
    provider: asString(raw.provider, "") || undefined,
    sourceCount: asNumber(raw.sourceCount, asNumber(raw.source_count, 0)) || undefined,
    confidence: asNumber(raw.confidence, 0) || undefined,
    fallbackUsed: asBoolean(raw.fallbackUsed, asBoolean(raw.fallback_used, false)),
    metadata: typeof raw.metadata === "object" && raw.metadata !== null ? (raw.metadata as RuntimeEventEnvelope["metadata"]) : undefined,
  };
}

export function normalizeRuntimeEvents(rawEvents: RawEvent[]): RuntimeEventEnvelope[] {
  return rawEvents.map((event, index) => normalizeRuntimeEvent(event, index));
}

export function safeSessionId(events: RuntimeEventEnvelope[]): string {
  return events[0]?.sessionId ?? "session-unknown";
}
