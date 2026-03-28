import { describe, expect, it } from "vitest";

import { normalizeRuntimeEvent, normalizeRuntimeEvents } from "../normalization";

describe("runtime insight normalization", () => {
  it("normalizes snake_case and camelCase fields", () => {
    const normalized = normalizeRuntimeEvent(
      {
        id: "evt-1",
        session_id: "sess-1",
        event: "tool_result",
        agent: "SearchSkill",
        detail: "search done",
        at: "2026-03-29T00:00:00.000Z",
        duration_ms: 120,
        source_count: 3,
        fallback_used: true,
      },
      0,
    );

    expect(normalized.sessionId).toBe("sess-1");
    expect(normalized.kind).toBe("tool_result");
    expect(normalized.phase).toBe("execution");
    expect(normalized.sourceCount).toBe(3);
    expect(normalized.fallbackUsed).toBe(true);
  });

  it("normalizes arrays and preserves order", () => {
    const normalized = normalizeRuntimeEvents([
      {
        id: "evt-1",
        sessionId: "sess-1",
        kind: "thinking",
        agent: "OrchestratorAgent",
        detail: "plan",
        at: "2026-03-29T00:00:00.000Z",
      },
      {
        id: "evt-2",
        sessionId: "sess-1",
        kind: "done",
        actor: "synthesizer",
        detail: "complete",
        at: "2026-03-29T00:00:01.000Z",
      },
    ]);

    expect(normalized).toHaveLength(2);
    expect(normalized[0]?.id).toBe("evt-1");
    expect(normalized[1]?.kind).toBe("done");
  });
});
