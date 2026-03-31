import { ZodError } from "zod";
import {
  chatMessageSchema,
  runChatRequestSchema,
  traceEventListSchema,
  traceEventSchema,
  type ChatMessageRecord,
  type MessageRole,
  type RunChatRequestRecord,
  type TraceEventRecord,
  type TraceEventType,
} from "./chat-schemas";

export const INITIAL_TRACE_WINDOW = 24;
export const TRACE_WINDOW_STEP = 18;

const IMPORTANT_EVENTS = new Set<TraceEventType>([
  "thinking",
  "tool_call",
  "node_start",
  "node_done",
  "subagent_start",
  "subagent_done",
  "artifact_created",
  "artifact_updated",
  "waiting",
  "done",
]);

const DEFAULT_ASSISTANT_MESSAGE =
  "Hello, I am Glass Box Chat. Send a question and the backend will process the pipeline and stream trace events over SSE.";

export type TraceMessageSection = {
  messageId: string;
  events: TraceEventRecord[];
};

export type TraceSessionSection = {
  sessionId: string;
  sessionLabel: string;
  events: TraceEventRecord[];
};

export type TraceSessionGroupedByMessage = {
  sessionId: string;
  sessionLabel: string;
  messages: TraceMessageSection[];
};

export class ChatMessageModel {
  private constructor(private readonly value: ChatMessageRecord) {}

  static assistant(
    content: string,
    id = `assistant-${crypto.randomUUID()}`,
    sources?: string[],
    sourceDetails?: Array<{ title: string; url: string; freshness: string }>,
  ): ChatMessageModel {
    return new ChatMessageModel(
      chatMessageSchema.parse({
        id,
        role: "assistant",
        content,
        ...(sources && sources.length > 0 ? { sources } : {}),
        ...(sourceDetails && sourceDetails.length > 0 ? { sourceDetails } : {}),
      }),
    );
  }

  static user(content: string, id = `user-${crypto.randomUUID()}`): ChatMessageModel {
    return new ChatMessageModel(
      chatMessageSchema.parse({
        id,
        role: "user",
        content,
      }),
    );
  }

  static fromUnknown(input: unknown): ChatMessageModel {
    return new ChatMessageModel(chatMessageSchema.parse(input));
  }

  static initialAssistantMessage(): ChatMessageRecord {
    return ChatMessageModel.assistant(DEFAULT_ASSISTANT_MESSAGE, "assistant-welcome").toJSON();
  }

  static getContentValidationMessage(role: MessageRole, content: string): string | null {
    const result = chatMessageSchema.safeParse({
      id: "preview",
      role,
      content,
    });

    if (result.success) {
      return null;
    }

    return ChatMessageModel.extractFirstIssue(result.error);
  }

  static extractFirstIssue(error: ZodError): string {
    return error.issues[0]?.message ?? "Dữ liệu tin nhắn không hợp lệ.";
  }

  toJSON(): ChatMessageRecord {
    return { ...this.value };
  }
}

export class RunChatRequestModel {
  private constructor(private readonly value: RunChatRequestRecord) {}

  static fromPrompt(prompt: string, sessionId: string, messageId: string): RunChatRequestModel {
    return new RunChatRequestModel(runChatRequestSchema.parse({ prompt, sessionId, messageId }));
  }

  static fromUnknown(input: unknown): RunChatRequestModel {
    return new RunChatRequestModel(runChatRequestSchema.parse(input));
  }

  static getValidationMessage(prompt: string, sessionId: string = ""): string | null {
    const result = runChatRequestSchema.safeParse({ prompt, sessionId: sessionId || "dummy-session", messageId: "dummy-message-id" });
    if (result.success) {
      return null;
    }

    return RunChatRequestModel.extractFirstIssue(result.error);
  }

  static extractFirstIssue(error: ZodError): string {
    return error.issues[0]?.message ?? "Chat request is invalid.";
  }

  get prompt(): string {
    return this.value.prompt;
  }

  toJSON(): RunChatRequestRecord {
    return { ...this.value };
  }
}

export class TraceEventModel {
  private constructor(private readonly value: TraceEventRecord) {}

  static bootstrap(): TraceEventRecord {
    return new TraceEventModel(
      traceEventSchema.parse({
        id: "trace-bootstrap",
        event: "agent_start",
        detail: "Runtime Trace is ready. Waiting for the user's first question.",
        agent: "CoordinatorAgent",
        branch: "main",
        mode: "sequential",
        createdAt: new Date().toLocaleTimeString(),
        sessionId: "system",
        sessionLabel: "System",
        messageId: "msg-system",
      }),
    ).toJSON();
  }

  static fromUnknown(input: unknown): TraceEventModel {
    return new TraceEventModel(traceEventSchema.parse(input));
  }

  static parseList(input: unknown): TraceEventRecord[] {
    return traceEventListSchema.parse(input);
  }

  static groupVisible(events: TraceEventRecord[], visibleTraceCount: number): TraceSessionSection[] {
    const visibleEvents = events.slice(Math.max(0, events.length - visibleTraceCount));

    return visibleEvents.reduce<TraceSessionSection[]>((sections, event) => {
      const lastSection = sections[sections.length - 1];

      if (lastSection?.sessionId === event.sessionId) {
        lastSection.events.push(event);
        return sections;
      }

      sections.push({
        sessionId: event.sessionId,
        sessionLabel: event.sessionLabel,
        events: [event],
      });

      return sections;
    }, []);
  }

  static groupVisibleByMessage(events: TraceEventRecord[], visibleTraceCount: number): TraceSessionGroupedByMessage[] {
    const visibleEvents = events.slice(Math.max(0, events.length - visibleTraceCount));

    return visibleEvents.reduce<TraceSessionGroupedByMessage[]>((sessions, event) => {
      let session = sessions.find(s => s.sessionId === event.sessionId);

      if (!session) {
        session = {
          sessionId: event.sessionId,
          sessionLabel: event.sessionLabel,
          messages: [],
        };
        sessions.push(session);
      }

      let message = session.messages.find(m => m.messageId === event.messageId);

      if (!message) {
        message = {
          messageId: event.messageId,
          events: [],
        };
        session.messages.push(message);
      }

      message.events.push(event);

      return sessions;
    }, []);
  }

  static splitPrimaryAndSupporting(events: TraceEventRecord[]) {
    const primary = events.filter((event, index) => IMPORTANT_EVENTS.has(event.event) || index === events.length - 1);
    const primaryIds = new Set(primary.map((event) => event.id));
    const supporting = events.filter((event) => !primaryIds.has(event.id));

    return { primary, supporting };
  }

  toJSON(): TraceEventRecord {
    return { ...this.value };
  }
}

export const initialAssistantMessage = ChatMessageModel.initialAssistantMessage();