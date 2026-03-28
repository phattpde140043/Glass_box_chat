type RequestBodyPreview =
  | null
  | string
  | number
  | boolean
  | Record<string, unknown>
  | Array<unknown>;

function parseJsonSafely(value: string): RequestBodyPreview {
  try {
    return JSON.parse(value) as RequestBodyPreview;
  } catch {
    return value;
  }
}

function toBodyPreview(body: BodyInit | null | undefined): RequestBodyPreview {
  if (typeof body === "undefined" || body === null) {
    return null;
  }

  if (typeof body === "string") {
    return parseJsonSafely(body);
  }

  if (body instanceof URLSearchParams) {
    return body.toString();
  }

  if (body instanceof FormData) {
    return Object.fromEntries(body.entries());
  }

  return "[non-text body]";
}

function toRequestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") {
    return input;
  }

  if (input instanceof URL) {
    return input.toString();
  }

  return input.url;
}

export async function fetchWithRequestLog(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const method = (init?.method || "GET").toUpperCase();
  const url = toRequestUrl(input);

  console.log("[API request]", {
    method,
    url,
    body: toBodyPreview(init?.body),
  });

  return fetch(input, init);
}