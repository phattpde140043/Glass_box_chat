export type FetchFunction = typeof fetch;

export async function fetchWithTimeout(
  fetchFn: FetchFunction,
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetchFn(url, {
      ...init,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function withRetry<T>(
  operation: () => Promise<T>,
  maxRetries: number,
  baseDelayMs = 150,
): Promise<T> {
  let lastError: unknown;

  for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      lastError = error;
      if (attempt >= maxRetries) {
        break;
      }

      const waitMs = baseDelayMs * (attempt + 1);
      await new Promise((resolve) => setTimeout(resolve, waitMs));
    }
  }

  if (lastError instanceof Error) {
    throw lastError;
  }

  throw new Error("Operation failed after retries.");
}
