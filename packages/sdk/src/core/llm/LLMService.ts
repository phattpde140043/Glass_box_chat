import type { LLMEvent, LLMProvider, LLMRequest, LLMResponse } from "./types";

/**
 * Service layer wrapping an LLMProvider.
 * The service is provider-agnostic: it depends on the LLMProvider interface,
 * not on any concrete implementation (Gemini, Claude, …).
 */
export class LLMService {
  constructor(private readonly provider: LLMProvider) {}

  async generate(request: LLMRequest): Promise<LLMResponse> {
    if (!request.messages.length) {
      throw new Error("LLMService: messages must not be empty.");
    }
    return this.provider.generate(request);
  }

  async *stream(request: LLMRequest): AsyncIterable<LLMEvent> {
    if (!request.messages.length) {
      throw new Error("LLMService: messages must not be empty.");
    }
    yield* this.provider.stream(request);
  }
}
