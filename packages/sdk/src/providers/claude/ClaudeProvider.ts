import { mapToEvents } from "../../core/llm/mapper";
import type { LLMEvent, LLMMessage, LLMProvider, LLMRequest, LLMResponse } from "../../core/llm/types";
import { fetchWithTimeout, type FetchFunction, withRetry } from "../shared/http";
import { splitMessages } from "../shared/message-normalizer";

type ClaudeProviderOptions = {
  apiKey?: string;
  model?: string;
  endpointUrl?: string;
  anthropicVersion?: string;
  timeoutMs?: number;
  maxRetries?: number;
  thinkingMessage?: string;
  defaultMaxTokens?: number;
  fetchFn?: FetchFunction;
};

type ClaudeMessage = {
  role: "user" | "assistant";
  content: string;
};

type ClaudeRequestBody = {
  model: string;
  system?: string;
  messages: ClaudeMessage[];
  max_tokens: number;
  temperature?: number;
};

type ClaudeTextContent = {
  type: "text";
  text: string;
};

type ClaudeResponseBody = {
  content?: ClaudeTextContent[];
  error?: {
    message?: string;
  };
};

const DEFAULT_MODEL = "claude-3-5-sonnet-latest";
const DEFAULT_ENDPOINT_URL = "https://api.anthropic.com/v1/messages";
const DEFAULT_ANTHROPIC_VERSION = "2023-06-01";
const DEFAULT_TIMEOUT_MS = 30_000;
const DEFAULT_MAX_RETRIES = 2;
const DEFAULT_MAX_TOKENS = 1024;

function assertApiKey(value: string | undefined): string {
  const apiKey = value?.trim() ?? process.env.ANTHROPIC_API_KEY?.trim();
  if (!apiKey) {
    throw new Error("Claude API key is required. Set ANTHROPIC_API_KEY or pass apiKey in ClaudeProvider options.");
  }

  return apiKey;
}

function buildClaudeMessages(messages: LLMMessage[]): { system?: string; messages: ClaudeMessage[] } {
  const normalized = splitMessages(messages, (role) => (role === "assistant" ? "assistant" : "user"));

  const conversation: ClaudeMessage[] = normalized.conversation.map((message) => ({
    role: message.role,
    content: message.content,
  }));

  return {
    system: normalized.systemText,
    messages: conversation,
  };
}

function extractClaudeText(response: ClaudeResponseBody): string {
  const text = (response.content ?? [])
    .filter((item) => item.type === "text")
    .map((item) => item.text)
    .join("")
    .trim();

  if (!text) {
    throw new Error("Claude returned an empty response.");
  }

  return text;
}

export class ClaudeProvider implements LLMProvider {
  private readonly apiKey: string;
  private readonly model: string;
  private readonly endpointUrl: string;
  private readonly anthropicVersion: string;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly thinkingMessage: string;
  private readonly defaultMaxTokens: number;
  private readonly fetchFn: FetchFunction;

  constructor(options: ClaudeProviderOptions = {}) {
    this.apiKey = assertApiKey(options.apiKey);
    this.model = options.model ?? DEFAULT_MODEL;
    this.endpointUrl = options.endpointUrl ?? DEFAULT_ENDPOINT_URL;
    this.anthropicVersion = options.anthropicVersion ?? DEFAULT_ANTHROPIC_VERSION;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.maxRetries = options.maxRetries ?? DEFAULT_MAX_RETRIES;
    this.thinkingMessage = options.thinkingMessage ?? "Processing...";
    this.defaultMaxTokens = options.defaultMaxTokens ?? DEFAULT_MAX_TOKENS;
    this.fetchFn = options.fetchFn ?? fetch;
  }

  async generate(request: LLMRequest): Promise<LLMResponse> {
    const payload = this.toClaudeRequest(request);

    try {
      return await withRetry(async () => {
        const response = await fetchWithTimeout(this.fetchFn, this.endpointUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-api-key": this.apiKey,
            "anthropic-version": this.anthropicVersion,
          },
          body: JSON.stringify(payload),
        }, this.timeoutMs);

        const body = (await response.json()) as ClaudeResponseBody;

        if (!response.ok) {
          const errorMessage = body.error?.message ?? `Claude request failed with HTTP ${response.status}.`;
          throw new Error(errorMessage);
        }

        return { content: extractClaudeText(body) };
      }, this.maxRetries);
    } catch (error) {
      const fallbackMessage = error instanceof Error ? error.message : "Unknown Claude provider error.";
      throw new Error(`Claude generate failed after retries: ${fallbackMessage}`);
    }
  }

  async *stream(request: LLMRequest): AsyncIterable<LLMEvent> {
    const response = await this.generate(request);
    for (const event of mapToEvents(response.content, { thinkingMessage: this.thinkingMessage })) {
      yield event;
    }
  }

  private toClaudeRequest(request: LLMRequest): ClaudeRequestBody {
    const base = buildClaudeMessages(request.messages);

    return {
      model: this.model,
      messages: base.messages,
      system: base.system,
      temperature: request.temperature,
      max_tokens: request.maxTokens ?? this.defaultMaxTokens,
    };
  }

}

export type { ClaudeProviderOptions };
