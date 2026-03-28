import { NextRequest, NextResponse } from "next/server";
import { RunChatRequestModel } from "../../../../../models/chat-run-request";

export const runtime = "nodejs";

function buildBackendUrl(path: string): string {
  const baseUrl =
    process.env.API_BASE_URL?.trim() || process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || "http://localhost:8000";

  return `${baseUrl}${path}`;
}

export async function POST(request: NextRequest) {
  let payload: ReturnType<RunChatRequestModel["toJSON"]>;

  try {
    const body = (await request.json()) as unknown;
    payload = RunChatRequestModel.fromUnknown(body).toJSON();
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : "Request payload is invalid.";
    return NextResponse.json({ error: errorMessage }, { status: 400 });
  }

  let upstreamResponse: Response;

  try {
    upstreamResponse = await fetch(buildBackendUrl("/run"), {
      method: "POST",
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      { error: "Cannot connect to the runtime backend. Please verify the API service is running." },
      { status: 502 },
    );
  }

  if (!upstreamResponse.ok) {
    return NextResponse.json(
      { error: `Runtime backend returned HTTP ${upstreamResponse.status}.` },
      { status: upstreamResponse.status },
    );
  }

  if (!upstreamResponse.body) {
    return NextResponse.json({ error: "Runtime backend did not return a valid stream." }, { status: 502 });
  }

  return new Response(upstreamResponse.body, {
    headers: {
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "Content-Type": "text/event-stream; charset=utf-8",
    },
  });
}
