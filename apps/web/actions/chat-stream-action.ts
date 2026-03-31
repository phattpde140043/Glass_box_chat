import { RunChatRequestModel } from "../models/chat-run-request";
import { TraceEventModel } from "../models/trace-event";
import { fetchWithRequestLog } from "../services/api-client";
import { consumeEventStream } from "../services/event-stream";
import {
  assistantMessagePayloadSchema,
  streamErrorPayloadSchema,
  type TraceEventRecord,
} from "../validation/chat-schemas";

type RunChatStreamHandlers = {
  onAssistantMessage: (
    content: string,
    sources?: string[],
    sourceDetails?: Array<{ title: string; url: string; freshness: string }>,
  ) => void;
  onTraceEvent: (event: TraceEventRecord) => void;
};

type RouteErrorPayload = {
  error?: string;
};

function toErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return "An unknown error occurred while communicating with the API.";
}

async function extractRouteError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as RouteErrorPayload;
    if (typeof payload.error === "string" && payload.error.trim().length > 0) {
      return payload.error;
    }
  } catch {
    return `Internal API returned HTTP error ${response.status}.`;
  }

  return `Internal API returned HTTP error ${response.status}.`;
}

export async function runChatStream(
  prompt: string,
  handlers: RunChatStreamHandlers & { sessionId?: string; messageId?: string }
): Promise<void> {
  // Accept sessionId and messageId and include in payload if provided
  const sessionId = handlers.sessionId || "dummy-session";
  const messageId = handlers.messageId || `msg-${crypto.randomUUID()}`;
  const payload = RunChatRequestModel.fromPrompt(prompt, sessionId, messageId).toJSON();

  const response = await fetchWithRequestLog("/api/chat/run", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(await extractRouteError(response));
  }

  if (!response.body) {
    throw new Error("No response stream received from the internal API.");
  }

  await consumeEventStream(response.body, {
    onEvent: ({ event, data }) => {
      const parsedPayload = JSON.parse(data) as unknown;

      if (event === "message") {
        handlers.onTraceEvent(TraceEventModel.fromUnknown(parsedPayload).toJSON());
        return;
      }

      if (event === "done") {
        const assistantPayload = assistantMessagePayloadSchema.parse(parsedPayload);
        handlers.onAssistantMessage(assistantPayload.content, assistantPayload.sources, assistantPayload.sourceDetails);
        return;
      }

      if (event === "error") {
        const errorPayload = streamErrorPayloadSchema.parse(parsedPayload);
        throw new Error(errorPayload.error);
      }

      throw new Error(`Received unsupported SSE event type: ${event}`);
    },
  }).catch((error) => {
    throw new Error(toErrorMessage(error));
  });
}