import { mapToEvents } from "../../core/llm/mapper";
import type { LLMEvent, LLMMessage, LLMProvider, LLMRequest, LLMResponse } from "../../core/llm/types";
import { fetchWithTimeout, type FetchFunction, withRetry } from "../shared/http";
import { splitMessages } from "../shared/message-normalizer";

type GeminiProviderOptions = {
  apiKey?: string;
  model?: string;
  endpointBaseUrl?: string;
  timeoutMs?: number;
  maxRetries?: number;
  thinkingMessage?: string;
  fetchFn?: FetchFunction;
};

type GeminiPart = {
  text?: string;
  thought?: boolean;
};

type GeminiContent = {
  role?: "user" | "model";
  parts: GeminiPart[];
};

type GeminiGenerateRequest = {
  systemInstruction?: {
    parts: GeminiPart[];
  };
  contents: GeminiContent[];
  generationConfig?: {
    temperature?: number;
    maxOutputTokens?: number;
  };
};

type GeminiGenerateResponse = {
  candidates?: Array<{
    content?: GeminiContent;
  }>;
  error?: {
    message?: string;
  };
};

const DEFAULT_MODEL = "gemini-2.5-flash";
const DEFAULT_ENDPOINT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta";
const DEFAULT_TIMEOUT_MS = 30_000;
const DEFAULT_MAX_RETRIES = 2;

function assertApiKey(value: string | undefined): string {
  const apiKey = value?.trim() ?? process.env.GEMINI_API_KEY?.trim();
  if (!apiKey) {
    throw new Error("Gemini API key is required. Set GEMINI_API_KEY or pass apiKey in GeminiProvider options.");
  }

  return apiKey;
}

function buildGeminiContents(messages: LLMMessage[]): GeminiGenerateRequest {
  const normalized = splitMessages(messages, (role) => (role === "assistant" ? "model" : "user"));

  const contents: GeminiContent[] = normalized.conversation.map((message) => ({
    role: message.role,
    parts: [{ text: message.content }],
  }));

  if (!normalized.systemText) {
    return { contents };
  }

  return {
    systemInstruction: {
      parts: [{ text: normalized.systemText }],
    },
    contents,
  };
}

function extractCandidateText(response: GeminiGenerateResponse): string {
  const candidate = response.candidates?.[0];
  const parts = candidate?.content?.parts ?? [];
  // Filter out thinking/thought parts (gemini-2.5+ thinking models)
  const text = parts
    .filter((part) => !part.thought)
    .map((part) => part.text ?? "")
    .join("")
    .trim();

  if (!text) {
    throw new Error("Gemini returned an empty response.");
  }

  return text;
}

export class GeminiProvider implements LLMProvider {
  private readonly apiKey: string;
  private readonly model: string;
  private readonly endpointBaseUrl: string;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly thinkingMessage: string;
  private readonly fetchFn: FetchFunction;

  constructor(options: GeminiProviderOptions = {}) {
    this.apiKey = assertApiKey(options.apiKey);
    this.model = options.model ?? DEFAULT_MODEL;
    this.endpointBaseUrl = options.endpointBaseUrl ?? DEFAULT_ENDPOINT_BASE_URL;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.maxRetries = options.maxRetries ?? DEFAULT_MAX_RETRIES;
    this.thinkingMessage = options.thinkingMessage ?? "Processing...";
    this.fetchFn = options.fetchFn ?? fetch;
  }

  async generate(request: LLMRequest): Promise<LLMResponse> {
    const payload = this.toGeminiRequest(request);
    const url = `${this.endpointBaseUrl}/models/${this.model}:generateContent?key=${this.apiKey}`;

    try {
      return await withRetry(async () => {
        const response = await fetchWithTimeout(this.fetchFn, url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        }, this.timeoutMs);

        const body = (await response.json()) as GeminiGenerateResponse;

        if (!response.ok) {
          const errorMessage = body.error?.message ?? `Gemini request failed with HTTP ${response.status}.`;
          throw new Error(errorMessage);
        }

        return { content: extractCandidateText(body) };
      }, this.maxRetries);
    } catch (error) {
      const fallbackMessage = error instanceof Error ? error.message : "Unknown Gemini provider error.";
      throw new Error(`Gemini generate failed after retries: ${fallbackMessage}`);
    }
  }

  async *stream(request: LLMRequest): AsyncIterable<LLMEvent> {
    // Gemini generateContent is used as baseline; stream is normalized via mapper for provider parity.
    const response = await this.generate(request);
    for (const event of mapToEvents(response.content, { thinkingMessage: this.thinkingMessage })) {
      yield event;
    }
  }

  private toGeminiRequest(request: LLMRequest): GeminiGenerateRequest {
    const base = buildGeminiContents(request.messages);
    const generationConfig: GeminiGenerateRequest["generationConfig"] = {
      temperature: request.temperature,
      maxOutputTokens: request.maxTokens,
    };

    return {
      ...base,
      generationConfig,
    };
  }

}

export type { GeminiProviderOptions };
