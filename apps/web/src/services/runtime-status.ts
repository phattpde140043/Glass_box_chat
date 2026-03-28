export type RuntimeStatus = {
  status: "ok" | "degraded" | "offline";
  backendReachable: boolean;
  backendStatusCode: number | null;
  checkedAt: string | null;
};

function normalizeStatus(value: unknown): RuntimeStatus["status"] {
  if (value === "ok" || value === "degraded" || value === "offline") {
    return value;
  }

  return "offline";
}

export async function loadRuntimeStatus(): Promise<RuntimeStatus> {
  const response = await fetch("/api/chat/health", {
    cache: "no-store",
  });

  if (!response.ok) {
    return {
      status: "offline",
      backendReachable: false,
      backendStatusCode: response.status,
      checkedAt: new Date().toISOString(),
    };
  }

  const payload = (await response.json()) as Partial<RuntimeStatus>;

  return {
    status: normalizeStatus(payload.status),
    backendReachable: payload.backendReachable === true,
    backendStatusCode: typeof payload.backendStatusCode === "number" ? payload.backendStatusCode : null,
    checkedAt: new Date().toISOString(),
  };
}
