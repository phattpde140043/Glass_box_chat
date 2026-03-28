export type RuntimeStatus = {
  status: "ok" | "degraded" | "offline";
  backendReachable: boolean;
  backendStatusCode: number | null;
  checkedAt: string | null;
};

const REQUEST_TIMEOUT_MS = 5000;

function normalizeStatus(value: unknown): RuntimeStatus["status"] {
  if (value === "ok" || value === "degraded" || value === "offline") {
    return value;
  }

  return "offline";
}

export async function loadRuntimeStatus(): Promise<RuntimeStatus> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let response: Response;

  try {
    response = await fetch("/api/chat/health", {
      cache: "no-store",
      signal: controller.signal,
    });
  } catch {
    return {
      status: "offline",
      backendReachable: false,
      backendStatusCode: null,
      checkedAt: new Date().toISOString(),
    };
  } finally {
    clearTimeout(timeoutId);
  }

  if (!response.ok) {
    return {
      status: "offline",
      backendReachable: false,
      backendStatusCode: response.status,
      checkedAt: new Date().toISOString(),
    };
  }

  let payload: Partial<RuntimeStatus> = {};

  try {
    payload = (await response.json()) as Partial<RuntimeStatus>;
  } catch {
    payload = {};
  }

  return {
    status: normalizeStatus(payload.status),
    backendReachable: payload.backendReachable === true,
    backendStatusCode: typeof payload.backendStatusCode === "number" ? payload.backendStatusCode : null,
    checkedAt: new Date().toISOString(),
  };
}
