import type { RuntimeEventEnvelope } from "../domain";

type FixtureSeed = {
  sessionId: string;
  baseTime: string;
  branch: "A" | "B" | "C" | "main";
};

function eventId(sessionId: string, index: number): string {
  return `${sessionId}-evt-${String(index).padStart(3, "0")}`;
}

function at(baseTimeIso: string, offsetMs: number): string {
  return new Date(Date.parse(baseTimeIso) + offsetMs).toISOString();
}

function createExecutionBurst(seed: FixtureSeed): RuntimeEventEnvelope[] {
  const steps: Array<Pick<RuntimeEventEnvelope, "kind" | "detail" | "actor" | "phase"> & Partial<RuntimeEventEnvelope>> = [
    {
      kind: "thinking",
      phase: "planning",
      actor: "coordinator",
      detail: "Analyze user prompt and infer task intent",
      durationMs: 120,
      confidence: 0.77,
    },
    {
      kind: "tool_call",
      phase: "execution",
      actor: "tool",
      detail: "Invoke search provider weather_open_meteo",
      durationMs: 340,
      provider: "weather_open_meteo",
      sourceCount: 0,
      confidence: 0.84,
    },
    {
      kind: "tool_result",
      phase: "execution",
      actor: "researcher",
      detail: "Weather provider returned current snapshot",
      durationMs: 510,
      provider: "weather_open_meteo",
      sourceCount: 3,
      cacheHit: false,
      confidence: 0.9,
    },
    {
      kind: "tool_call",
      phase: "execution",
      actor: "tool",
      detail: "Invoke newsapi provider for supporting context",
      durationMs: 220,
      provider: "newsapi",
      confidence: 0.66,
    },
    {
      kind: "fallback",
      phase: "execution",
      actor: "system",
      detail: "Primary provider rate-limited, route to duckduckgo",
      fallbackUsed: true,
      durationMs: 180,
      provider: "duckduckgo",
      attempts: 2,
      confidence: 0.49,
    },
    {
      kind: "tool_result",
      phase: "execution",
      actor: "researcher",
      detail: "DuckDuckGo returned fallback context and citations",
      durationMs: 920,
      provider: "duckduckgo",
      sourceCount: 4,
      fallbackUsed: true,
      confidence: 0.58,
    },
    {
      kind: "waiting",
      phase: "waiting",
      actor: "system",
      detail: "Waiting for synthesis completion",
      durationMs: 410,
      confidence: 0.64,
    },
    {
      kind: "done",
      phase: "delivery",
      actor: "synthesizer",
      detail: "Final answer generated with source references",
      durationMs: 350,
      confidence: 0.79,
      sourceCount: 4,
    },
  ];

  return steps.map((step, index) => ({
    id: eventId(seed.sessionId, index + 1),
    sessionId: seed.sessionId,
    branch: seed.branch,
    taskId: `${seed.sessionId}-task-1`,
    nodeId: `node-${index + 1}`,
    at: at(seed.baseTime, index * 800),
    cacheHit: step.cacheHit ?? false,
    metadata: {
      fixture: true,
      branch: seed.branch,
    },
    ...step,
  }));
}

function createSlowSession(seed: FixtureSeed): RuntimeEventEnvelope[] {
  const baseline = createExecutionBurst(seed);
  return baseline.map((event, index) => {
    if (index === 2 || index === 5) {
      return {
        ...event,
        kind: index === 2 ? "timeout" : "error",
        detail: index === 2 ? "Provider timed out after 10s" : "Provider failed with 502 upstream",
        durationMs: index === 2 ? 10200 : 14500,
        attempts: 3,
        confidence: 0.2,
      };
    }
    if (index === 7) {
      return {
        ...event,
        kind: "done",
        detail: "Response assembled with degraded source quality",
        durationMs: 1250,
        confidence: 0.43,
      };
    }
    return {
      ...event,
      durationMs: (event.durationMs ?? 0) + 600,
    };
  });
}

export function buildRuntimeInsightFixtureBySession(): Record<string, RuntimeEventEnvelope[]> {
  const s1 = createExecutionBurst({
    sessionId: "sess-alpha",
    baseTime: "2026-03-28T10:00:00.000Z",
    branch: "A",
  });

  const s2 = createSlowSession({
    sessionId: "sess-bravo",
    baseTime: "2026-03-28T10:30:00.000Z",
    branch: "B",
  });

  const s3 = createExecutionBurst({
    sessionId: "sess-charlie",
    baseTime: "2026-03-28T11:10:00.000Z",
    branch: "main",
  }).map((event, index) =>
    index % 3 === 0
      ? {
          ...event,
          cacheHit: true,
          detail: `${event.detail} (cache reused)`,
          durationMs: Math.max(20, (event.durationMs ?? 0) - 150),
        }
      : event,
  );

  return {
    [s1[0].sessionId]: s1,
    [s2[0].sessionId]: s2,
    [s3[0].sessionId]: s3,
  };
}

export function buildRuntimeInsightFixtureFlat(): RuntimeEventEnvelope[] {
  return Object.values(buildRuntimeInsightFixtureBySession()).flat();
}
