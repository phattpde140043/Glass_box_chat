import { fetchWithRequestLog } from "./api-client";

export type RuntimeHealth = {
  status: "ok" | "degraded" | "offline";
  backendReachable: boolean;
  backendStatusCode: number | null;
};

export async function loadRuntimeHealth(): Promise<RuntimeHealth> {
  const response = await fetchWithRequestLog("/api/chat/health", {
    cache: "no-store",
  });

  if (!response.ok) {
    return {
      status: "offline",
      backendReachable: false,
      backendStatusCode: response.status,
    };
  }

  const payload = (await response.json()) as Partial<RuntimeHealth>;

  return {
    status: payload.status === "ok" || payload.status === "degraded" || payload.status === "offline" ? payload.status : "offline",
    backendReachable: payload.backendReachable === true,
    backendStatusCode: typeof payload.backendStatusCode === "number" ? payload.backendStatusCode : null,
  };
}
