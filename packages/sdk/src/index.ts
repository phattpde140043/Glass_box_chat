export type SkillExecutionMode = "sequential" | "parallel";

export type SkillDefinition<TInput = unknown, TOutput = unknown> = {
  name: string;
  description: string;
  run: (input: TInput) => Promise<TOutput>;
};

export function defineSkill<TInput = unknown, TOutput = unknown>(definition: SkillDefinition<TInput, TOutput>) {
  return definition;
}

export type { LLMEvent, LLMMessage, LLMProvider, LLMRequest, LLMResponse } from "./core/llm/types";
export { mapToEvents } from "./core/llm/mapper";
export { createLLMProvider } from "./core/llm/factory";
export { LLMService } from "./core/llm/LLMService";
export type { CreateLLMProviderOptions, LLMProviderType } from "./core/llm/factory";
export { ClaudeProvider } from "./providers/claude/ClaudeProvider";
export type { ClaudeProviderOptions } from "./providers/claude/ClaudeProvider";
export { GeminiProvider } from "./providers/gemini/GeminiProvider";
export type { GeminiProviderOptions } from "./providers/gemini/GeminiProvider";