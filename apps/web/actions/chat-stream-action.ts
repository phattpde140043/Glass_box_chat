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

  return "Đã xảy ra lỗi không xác định khi giao tiếp với API.";
}

async function extractRouteError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as RouteErrorPayload;
    if (typeof payload.error === "string" && payload.error.trim().length > 0) {
      return payload.error;
    }
  } catch {
    return `API nội bộ trả về lỗi HTTP ${response.status}.`;
  }

  return `API nội bộ trả về lỗi HTTP ${response.status}.`;
}

export async function runChatStream(prompt: string, handlers: RunChatStreamHandlers): Promise<void> {
  const payload = RunChatRequestModel.fromPrompt(prompt).toJSON();

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
    throw new Error("Không nhận được stream phản hồi từ API nội bộ.");
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

      throw new Error(`Nhận được loại SSE event không hỗ trợ: ${event}`);
    },
  }).catch((error) => {
    throw new Error(toErrorMessage(error));
  });
}