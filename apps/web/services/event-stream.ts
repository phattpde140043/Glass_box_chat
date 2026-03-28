export type ParsedServerEvent = {
  event: string;
  data: string;
};

type EventStreamHandlers = {
  onEvent: (event: ParsedServerEvent) => void | Promise<void>;
};

export async function consumeEventStream(
  stream: ReadableStream<Uint8Array>,
  handlers: EventStreamHandlers,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();

  let buffer = "";
  let currentEvent = "";
  let currentDataLines: string[] = [];

  const flushEvent = async () => {
    if (!currentEvent || currentDataLines.length === 0) {
      currentEvent = "";
      currentDataLines = [];
      return;
    }

    const data = currentDataLines.join("\n");
    await handlers.onEvent({
      event: currentEvent,
      data,
    });

    currentEvent = "";
    currentDataLines = [];
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (line.length === 0) {
          await flushEvent();
          continue;
        }

        if (line.startsWith("event:")) {
          currentEvent = line.slice("event:".length).trim();
          continue;
        }

        if (line.startsWith("data:")) {
          currentDataLines.push(line.slice("data:".length).trimStart());
        }
      }
    }

    if (buffer.trim().length > 0) {
      const trailingLines = buffer.split(/\r?\n/);
      for (const line of trailingLines) {
        if (line.startsWith("event:")) {
          currentEvent = line.slice("event:".length).trim();
        } else if (line.startsWith("data:")) {
          currentDataLines.push(line.slice("data:".length).trimStart());
        }
      }
    }

    await flushEvent();
  } finally {
    reader.releaseLock();
  }
}