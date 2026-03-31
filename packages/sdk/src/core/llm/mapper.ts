import type { LLMEvent } from "./types";

export type EventMapperOptions = {
  thinkingMessage?: string;
};

export function mapToEvents(text: string, options: EventMapperOptions = {}): LLMEvent[] {
  const thinkingMessage = options.thinkingMessage ?? "Analyzing input...";

  return [
    { type: "thinking", content: thinkingMessage },
    { type: "message", content: text },
    { type: "done" },
  ];
}
