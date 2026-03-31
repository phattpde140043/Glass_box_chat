export type LLMMessage = {
  role: "system" | "user" | "assistant";
  content: string;
};

export type LLMRequest = {
  messages: LLMMessage[];
  temperature?: number;
  maxTokens?: number;
};

export type LLMResponse = {
  content: string;
};

export type LLMEvent =
  | { type: "thinking"; content: string }
  | { type: "message"; content: string }
  | { type: "done" };

export interface LLMProvider {
  generate(request: LLMRequest): Promise<LLMResponse>;
  stream(request: LLMRequest): AsyncIterable<LLMEvent>;
}
