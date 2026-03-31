import type { LLMMessage } from "../../core/llm/types";

export type SplitMessageResult<TConversationRole extends string> = {
  systemText?: string;
  conversation: Array<{
    role: TConversationRole;
    content: string;
  }>;
};

export function splitMessages<TConversationRole extends string>(
  messages: LLMMessage[],
  mapConversationRole: (role: Exclude<LLMMessage["role"], "system">) => TConversationRole,
): SplitMessageResult<TConversationRole> {
  const systemMessages = messages
    .filter((message) => message.role === "system")
    .map((message) => message.content.trim())
    .filter((message) => message.length > 0);

  const conversation = messages
    .filter((message): message is Extract<LLMMessage, { role: "user" | "assistant" }> => message.role !== "system")
    .map((message) => ({
      role: mapConversationRole(message.role),
      content: message.content,
    }));

  if (conversation.length === 0) {
    throw new Error("LLM request must include at least one user or assistant message.");
  }

  return {
    systemText: systemMessages.length > 0 ? systemMessages.join("\n\n") : undefined,
    conversation,
  };
}
