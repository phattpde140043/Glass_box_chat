import { NextResponse } from "next/server";

export const runtime = "nodejs";

function buildBackendUrl(path: string): string {
  const baseUrl =
    process.env.API_BASE_URL?.trim() || process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || "http://localhost:8000";

  return `${baseUrl}${path}`;
}

export async function GET() {
  try {
    const response = await fetch(buildBackendUrl("/health"), {
      method: "GET",
      cache: "no-store",
    });

    if (!response.ok) {
      return NextResponse.json(
        {
          status: "degraded",
          backendReachable: true,
          backendStatusCode: response.status,
        },
        { status: 200 },
      );
    }

    const payload = (await response.json()) as Record<string, unknown>;
    return NextResponse.json(
      {
        status: typeof payload.status === "string" ? payload.status : "ok",
        backendReachable: true,
        backendStatusCode: response.status,
      },
      { status: 200 },
    );
  } catch {
    return NextResponse.json(
      {
        status: "offline",
        backendReachable: false,
        backendStatusCode: null,
      },
      { status: 200 },
    );
  }
}
