import { TraceEventModel } from "../models/trace-event";
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
    throw new Error(`Không tải được danh sách session từ backend: HTTP ${sessionsResponse.status}`);
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
