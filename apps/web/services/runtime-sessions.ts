import { fetchWithRequestLog } from "./api-client";

export type RuntimeSessionSummary = {
  id: string;
};

function normalizeSessions(items: unknown): RuntimeSessionSummary[] {
  if (!Array.isArray(items)) {
    return [];
  }

  const seen = new Set<string>();

  return items
    .filter((item): item is RuntimeSessionSummary => {
      return Boolean(item) && typeof item === "object" && typeof (item as { id?: unknown }).id === "string";
    })
    .filter((item) => {
      if (seen.has(item.id)) {
        return false;
      }

      seen.add(item.id);
      return true;
    })
    .sort((left, right) => right.id.localeCompare(left.id));
}

export async function loadRuntimeSessions(limit = 10): Promise<RuntimeSessionSummary[]> {
  const response = await fetchWithRequestLog(`/api/chat/sessions?limit=${limit}`, {
    cache: "no-store",
  });

  if (!response.ok) {
    return [];
  }

  const payload = (await response.json()) as { items?: RuntimeSessionSummary[] };
  return normalizeSessions(payload.items);
}
