import { fetchWithRequestLog } from "./api-client";

export type RuntimeSessionSummary = {
  id: string;
};

export async function loadRuntimeSessions(limit = 10): Promise<RuntimeSessionSummary[]> {
  const response = await fetchWithRequestLog(`/api/chat/sessions?limit=${limit}`, {
    cache: "no-store",
  });

  if (!response.ok) {
    return [];
  }

  const payload = (await response.json()) as { items?: RuntimeSessionSummary[] };
  return Array.isArray(payload.items) ? payload.items : [];
}
