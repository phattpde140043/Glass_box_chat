import { createLLMProvider } from "../core/llm/factory";

export async function runLLMProviderExample(): Promise<void> {
  const provider = createLLMProvider("gemini");

  const stream = provider.stream({
    messages: [{ role: "user", content: "Explain SSE vs WebSocket" }],
  });

  for await (const event of stream) {
    // Example integration point for trace runtime listeners.
    console.log(event);
  }
}
