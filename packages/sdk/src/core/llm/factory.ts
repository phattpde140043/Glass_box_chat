import type { LLMProvider } from "./types";
import { ClaudeProvider, type ClaudeProviderOptions } from "../../providers/claude/ClaudeProvider";
import { GeminiProvider, type GeminiProviderOptions } from "../../providers/gemini/GeminiProvider";

export type LLMProviderType = "gemini" | "claude";

export type CreateLLMProviderOptions = {
  gemini?: GeminiProviderOptions;
  claude?: ClaudeProviderOptions;
};

export function createLLMProvider(type: LLMProviderType, options: CreateLLMProviderOptions = {}): LLMProvider {
  switch (type) {
    case "gemini":
      return new GeminiProvider(options.gemini);
    case "claude":
      return new ClaudeProvider(options.claude);
    default:
      throw new Error(`Unsupported provider: ${String(type)}`);
  }
}
