import { z } from "zod";
import chatContractJson from "./chat-contract.json";

const chatContract = chatContractJson as unknown as {
  chatPrompt: {
    minLength: number;
    maxLength: number;
  };
  messageRoles: readonly ["user", "assistant"];
  traceEventTypes: readonly [
    "agent_start",
    "node_start",
    "subagent_start",
    "thinking",
    "tool_call",
    "tool_result",
    "node_done",
    "subagent_done",
    "artifact_created",
    "artifact_updated",
    "waiting",
    "done"
  ];
  traceBranches: readonly ["main", "A", "B", "C"];
  traceModes: readonly ["parallel", "sequential"];
  agentStatuses: readonly ["running", "waiting_user", "done"];
  assistantPayloadType: "assistant_message";
  artifactTypes: readonly ["plan", "evidence", "final_response", "report", "dataset", "other"];
  artifactStatuses: readonly ["created", "updated", "final"];
};

export const CHAT_CONTRACT = chatContract;

export const messageRoleSchema = z.enum(chatContract.messageRoles);
export const traceEventTypeSchema = z.enum(chatContract.traceEventTypes);
export const traceBranchSchema = z.enum(chatContract.traceBranches);
export const traceModeSchema = z.enum(chatContract.traceModes);
export const agentStatusSchema = z.enum(chatContract.agentStatuses);
export const artifactTypeSchema = z.enum(chatContract.artifactTypes);
export const artifactStatusSchema = z.enum(chatContract.artifactStatuses);

export const chatPromptSchema = z
  .string()
  .trim()
  .min(chatContract.chatPrompt.minLength, "Message cannot be empty.")
  .max(chatContract.chatPrompt.maxLength, `Message cannot exceed ${chatContract.chatPrompt.maxLength} characters.`);

export const runChatRequestSchema = z.object({
  prompt: chatPromptSchema,
  sessionId: z.string().trim().min(1, "Session ID is required."),
  messageId: z.string().trim().min(1, "Message ID is required."),
});

export const sourceDetailSchema = z.object({
  title: z.string().trim().min(1),
  url: z.string().trim().url(),
  freshness: z.string().trim().min(1),
});

export const artifactSchema = z.object({
  id: z.string().trim().min(1),
  type: artifactTypeSchema,
  title: z.string().trim().min(1),
  status: artifactStatusSchema,
  content: z.string().trim().min(1).optional(),
  url: z.string().trim().url().optional(),
  createdAt: z.string().trim().min(1),
});

const nullToUndefined = (value: unknown) => (value === null ? undefined : value);

export const traceMetadataSchema = z.object({
  nodeId: z.string().trim().min(1).optional(),
  skill: z.string().trim().min(1).optional(),
  deps: z.array(z.string().trim().min(1)).optional(),
  score: z.string().trim().min(1).optional(),
  provider: z.string().trim().min(1).optional(),
  sourceCount: z.number().int().nonnegative().optional(),
  citationCount: z.number().int().nonnegative().optional(),
  freshness: z.string().trim().min(1).optional(),
  fallbackUsed: z.boolean().optional(),
  cacheHit: z.boolean().optional(),
  durationMs: z.number().int().nonnegative().optional(),
  startedAtMs: z.number().int().nonnegative().optional(),
  attempts: z.number().int().nonnegative().optional(),
  success: z.boolean().optional(),
  citations: z.array(z.string().trim().url()).optional(),
  branch: z.string().trim().min(1).optional(),
  phase: z.string().trim().min(1).optional(),
  parentNodeId: z.string().trim().min(1).optional(),
  nodeCount: z.number().int().nonnegative().optional(),
});

export const chatMessageSchema = z.object({
  id: z.string().min(1),
  role: messageRoleSchema,
  content: z.string().trim().min(1, "Message content is invalid."),
  sources: z.array(z.string().trim().url()).max(12).optional(),
  sourceDetails: z.array(sourceDetailSchema).max(12).optional(),
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
  messageId: z.string().trim().min(1),
  metadata: z.preprocess(nullToUndefined, traceMetadataSchema.optional()),
  artifact: z.preprocess(nullToUndefined, artifactSchema.optional()),
});

export const traceEventListSchema = z.array(traceEventSchema);

export const assistantMessagePayloadSchema = z.object({
  type: z.literal(chatContract.assistantPayloadType),
  content: z.string().trim().min(1),
  sources: z.array(z.string().trim().url()).max(12).optional(),
  sourceDetails: z.array(sourceDetailSchema).max(12).optional(),
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
export type TraceMetadataRecord = z.infer<typeof traceMetadataSchema>;
export type ArtifactRecord = z.infer<typeof artifactSchema>;