import { NextRequest, NextResponse } from "next/server";
import { RunChatRequestModel } from "../../../../../models/chat-run-request";
import {
  assistantMessagePayloadSchema,
  streamErrorPayloadSchema,
  traceEventSchema,
} from "../../../../../validation/chat-schemas";

export const runtime = "nodejs";

const encoder = new TextEncoder();

function buildBackendUrl(path: string): string {
  const baseUrl =
    process.env.API_BASE_URL?.trim() || process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || "http://localhost:8000";

  return `${baseUrl}${path}`;
}

function formatSseEvent(event: string, data: string): string {
  return `event: ${event}\ndata: ${data}\n\n`;
}

function toErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return "Unable to process stream from runtime backend.";
}

type UpstreamErrorPayload = {
  error?: string;
  message?: string;
};

async function extractUpstreamError(response: Response): Promise<string> {
  const fallback = `Runtime backend returned HTTP ${response.status}.`;

  try {
    const payload = (await response.json()) as UpstreamErrorPayload;

    if (typeof payload.error === "string" && payload.error.trim().length > 0) {
      return payload.error;
    }

    if (typeof payload.message === "string" && payload.message.trim().length > 0) {
      return payload.message;
    }

    return fallback;
  } catch {
    try {
      const textPayload = await response.text();
      if (textPayload.trim().length > 0) {
        return textPayload.trim();
      }
    } catch {
      return fallback;
    }

    return fallback;
  }
}

function validateSsePayload(eventName: string, rawData: string): string {
  const parsedPayload = JSON.parse(rawData) as unknown;

  if (eventName === "message") {
    return JSON.stringify(traceEventSchema.parse(parsedPayload));
  }

  if (eventName === "done") {
    return JSON.stringify(assistantMessagePayloadSchema.parse(parsedPayload));
  }

  if (eventName === "error") {
    return JSON.stringify(streamErrorPayloadSchema.parse(parsedPayload));
  }

  throw new Error(`Unsupported SSE event received from backend: ${eventName}`);
}

function createValidatedSseStream(upstream: ReadableStream<Uint8Array>): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    async start(controller) {
      const reader = upstream.getReader();
      const decoder = new TextDecoder();

      let buffer = "";
      let currentEvent = "";
      let currentDataLines: string[] = [];

      const flushEvent = () => {
        if (!currentEvent || currentDataLines.length === 0) {
          currentEvent = "";
          currentDataLines = [];
          return;
        }

        const validatedPayload = validateSsePayload(currentEvent, currentDataLines.join("\n"));
        controller.enqueue(encoder.encode(formatSseEvent(currentEvent, validatedPayload)));
        currentEvent = "";
        currentDataLines = [];
      };

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split(/\r?\n/);
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (line.length === 0) {
              flushEvent();
              continue;
            }

            if (line.startsWith("event:")) {
              currentEvent = line.slice("event:".length).trim();
              continue;
            }

            if (line.startsWith("data:")) {
              currentDataLines.push(line.slice("data:".length).trimStart());
            }
          }
        }

        if (buffer.trim().length > 0) {
          const trailingLines = buffer.split(/\r?\n/);
          for (const line of trailingLines) {
            if (line.startsWith("event:")) {
              currentEvent = line.slice("event:".length).trim();
            } else if (line.startsWith("data:")) {
              currentDataLines.push(line.slice("data:".length).trimStart());
            }
          }
        }

        flushEvent();
        controller.close();
      } catch (error) {
        controller.enqueue(
          encoder.encode(
            formatSseEvent(
              "error",
              JSON.stringify({
                error: toErrorMessage(error),
              }),
            ),
          ),
        );
        controller.close();
      } finally {
        reader.releaseLock();
      }
    },
  });
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
    const errorMessage = await extractUpstreamError(upstreamResponse);
    return NextResponse.json(
      { error: errorMessage },
      { status: upstreamResponse.status },
    );
  }

  if (!upstreamResponse.body) {
    return NextResponse.json({ error: "Runtime backend did not return a valid stream." }, { status: 502 });
  }

  return new Response(createValidatedSseStream(upstreamResponse.body), {
    headers: {
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "Content-Type": "text/event-stream; charset=utf-8",
    },
  });
}
