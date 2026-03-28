import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const DEFAULT_SESSION_LIMIT = 10;
const MAX_SESSION_LIMIT = 50;

function buildBackendUrl(path: string): string {
  const baseUrl =
    process.env.API_BASE_URL?.trim() || process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || "http://localhost:8000";

  return `${baseUrl}${path}`;
}

function normalizeLimit(value: string | null): number {
  const parsed = Number(value ?? DEFAULT_SESSION_LIMIT);

  if (!Number.isFinite(parsed)) {
    return DEFAULT_SESSION_LIMIT;
  }

  return Math.min(MAX_SESSION_LIMIT, Math.max(1, Math.trunc(parsed)));
}

export async function GET(request: NextRequest) {
  const limit = normalizeLimit(request.nextUrl.searchParams.get("limit"));

  let upstreamResponse: Response;

  try {
    upstreamResponse = await fetch(buildBackendUrl(`/sessions?limit=${limit}`), {
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      {
        error: "Cannot connect to the runtime backend.",
        items: [],
      },
      { status: 502 },
    );
  }

  if (!upstreamResponse.ok) {
    return NextResponse.json(
      {
        error: `Runtime backend returned HTTP ${upstreamResponse.status}.`,
        items: [],
      },
      { status: upstreamResponse.status },
    );
  }

  const payload = (await upstreamResponse.json()) as { items?: unknown };

  return NextResponse.json({
    items: Array.isArray(payload.items) ? payload.items : [],
  });
}
