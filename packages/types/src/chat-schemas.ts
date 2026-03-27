import { z } from "zod";
import chatContractJson from "./chat-contract.json";

const chatContract = chatContractJson as unknown as {
  chatPrompt: {
    minLength: number;
    maxLength: number;
  };
  messageRoles: readonly ["user", "assistant"];
  traceEventTypes: readonly ["agent_start", "thinking", "tool_call", "tool_result", "waiting", "done"];
  traceBranches: readonly ["main", "A", "B", "C"];
  traceModes: readonly ["parallel", "sequential"];
  agentStatuses: readonly ["running", "waiting_user", "done"];
  assistantPayloadType: "assistant_message";
};

export const CHAT_CONTRACT = chatContract;

export const messageRoleSchema = z.enum(chatContract.messageRoles);
export const traceEventTypeSchema = z.enum(chatContract.traceEventTypes);
export const traceBranchSchema = z.enum(chatContract.traceBranches);
export const traceModeSchema = z.enum(chatContract.traceModes);
export const agentStatusSchema = z.enum(chatContract.agentStatuses);

export const chatPromptSchema = z
  .string()
  .trim()
  .min(chatContract.chatPrompt.minLength, "Message cannot be empty.")
  .max(chatContract.chatPrompt.maxLength, `Message cannot exceed ${chatContract.chatPrompt.maxLength} characters.`);

export const runChatRequestSchema = z.object({
  prompt: chatPromptSchema,
});

export const chatMessageSchema = z.object({
  id: z.string().min(1),
  role: messageRoleSchema,
  content: z.string().trim().min(1, "Message content is invalid."),
});

export const traceEventSchema = z.object({
  id: z.string().min(1),
  event: traceEventTypeSchema,
  detail: z.string().trim().min(1),
  agent: z.string().trim().min(1),
  branch: traceBranchSchema,
  mode: traceModeSchema,
  createdAt: z.string().trim().min(1),
  sessionId: z.string().trim().min(1),
  sessionLabel: z.string().trim().min(1),
});

export const traceEventListSchema = z.array(traceEventSchema);

export const assistantMessagePayloadSchema = z.object({
  type: z.literal(chatContract.assistantPayloadType),
  content: z.string().trim().min(1),
});

export const streamErrorPayloadSchema = z.object({
  error: z.string().trim().min(1),
});

export type AgentStatus = z.infer<typeof agentStatusSchema>;
export type ChatMessageRecord = z.infer<typeof chatMessageSchema>;
export type MessageRole = z.infer<typeof messageRoleSchema>;
export type RunChatRequestRecord = z.infer<typeof runChatRequestSchema>;
export type TraceEventRecord = z.infer<typeof traceEventSchema>;
export type TraceEventType = z.infer<typeof traceEventTypeSchema>;
