import { TraceEventModel } from "../models/trace-event";
import { EMPTY_RUNTIME_METRICS, type RuntimeMetrics } from "../models/runtime-metrics";
import { fetchWithRequestLog } from "./api-client";
import type { TraceEventRecord } from "../validation/chat-schemas";

type RuntimeSessionSummary = {
  id: string;
};

type RuntimeSessionsResponse = {
  items: RuntimeSessionSummary[];
};

type RuntimeSessionEventItem = {
  payload: string;
};

type RuntimeSessionEventsResponse = {
  items: RuntimeSessionEventItem[];
};

type RuntimeMetricsResponse = RuntimeMetrics;

function toNumber(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }

  return fallback;
}

function toStringOrNull(value: unknown, fallback: string | null): string | null {
  if (typeof value === "string") {
    return value;
  }

  return fallback;
}

function normalizeBreakerStates(value: unknown): Record<string, boolean> {
  if (!value || typeof value !== "object") {
    return {};
  }

  return Object.fromEntries(
    Object.entries(value).map(([key, state]) => [key, Boolean(state)]),
  );
}

function buildBackendUrl(path: string): string {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || "http://localhost:8000";
  return `${baseUrl}${path}`;
}

function isTraceEventPayload(payload: unknown): payload is TraceEventRecord {
  try {
    TraceEventModel.fromUnknown(payload);
    return true;
  } catch {
    return false;
  }
}

function parseEventPayload(rawPayload: string): TraceEventRecord | null {
  try {
    const parsed = JSON.parse(rawPayload) as unknown;
    if (!isTraceEventPayload(parsed)) {
      return null;
    }

    return TraceEventModel.fromUnknown(parsed).toJSON();
  } catch {
    return null;
  }
}

function dedupeTraceEvents(events: TraceEventRecord[]): TraceEventRecord[] {
  const seen = new Set<string>();
  return events.filter((event) => {
    if (seen.has(event.id)) {
      return false;
    }

    seen.add(event.id);
    return true;
  });
}

export async function loadRuntimeHistory(sessionLimit = 5): Promise<TraceEventRecord[]> {
  const sessionsResponse = await fetchWithRequestLog(buildBackendUrl(`/sessions?limit=${sessionLimit}`), {
    cache: "no-store",
  });

  if (!sessionsResponse.ok) {
    throw new Error(`Failed to load the session list from the backend: HTTP ${sessionsResponse.status}`);
  }

  const sessionsPayload = (await sessionsResponse.json()) as RuntimeSessionsResponse;
  const sessions = [...sessionsPayload.items].reverse();

  const eventResponses = await Promise.all(
    sessions.map(async (session) => {
      const response = await fetchWithRequestLog(buildBackendUrl(`/sessions/${session.id}/events?limit=500&offset=0`), {
        cache: "no-store",
      });

      if (!response.ok) {
        return [] as TraceEventRecord[];
      }

      const payload = (await response.json()) as RuntimeSessionEventsResponse;
      return payload.items
        .map((item) => parseEventPayload(item.payload))
        .filter((event): event is TraceEventRecord => event !== null);
    }),
  );

  return dedupeTraceEvents(eventResponses.flat());
}

export async function loadRuntimeMetrics(): Promise<RuntimeMetrics> {
  const response = await fetchWithRequestLog(buildBackendUrl("/runtime/metrics"), {
    cache: "no-store",
  });

  if (!response.ok) {
    return EMPTY_RUNTIME_METRICS;
  }

  const payload = (await response.json()) as Partial<RuntimeMetricsResponse>;

  return {
    total_runs: toNumber(payload.total_runs, EMPTY_RUNTIME_METRICS.total_runs),
    total_nodes_executed: toNumber(payload.total_nodes_executed, EMPTY_RUNTIME_METRICS.total_nodes_executed),
    cache_hits: toNumber(payload.cache_hits, EMPTY_RUNTIME_METRICS.cache_hits),
    cache_misses: toNumber(payload.cache_misses, EMPTY_RUNTIME_METRICS.cache_misses),
    timeouts: toNumber(payload.timeouts, EMPTY_RUNTIME_METRICS.timeouts),
    retries: toNumber(payload.retries, EMPTY_RUNTIME_METRICS.retries),
    fallback_routes: toNumber(payload.fallback_routes, EMPTY_RUNTIME_METRICS.fallback_routes),
    avg_node_duration_ms: toNumber(payload.avg_node_duration_ms, EMPTY_RUNTIME_METRICS.avg_node_duration_ms),
    last_execution_mode: toStringOrNull(payload.last_execution_mode, EMPTY_RUNTIME_METRICS.last_execution_mode) ?? "sequential",
    last_dag_node_count: toNumber(payload.last_dag_node_count, EMPTY_RUNTIME_METRICS.last_dag_node_count),
    last_completed_at: toStringOrNull(payload.last_completed_at, EMPTY_RUNTIME_METRICS.last_completed_at),
    breaker_states: normalizeBreakerStates(payload.breaker_states),
  };
}
