import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChatMessageList } from "./chat-message-list";

describe("ChatMessageList", () => {
  it("renders sourceDetails and prefers them over raw sources", () => {
    render(
      <ChatMessageList
        isSending={false}
        messages={[
          {
            id: "assistant-1",
            role: "assistant",
            content: "Tong hop ket qua.",
            sourceDetails: [
              {
                title: "Da Nang weather snapshot",
                url: "https://weather.example.local/da-nang",
                freshness: "today",
              },
            ],
            sources: ["https://fallback.example.local/only-url"],
          },
        ]}
      />,
    );

    expect(screen.getByText("Da Nang weather snapshot")).toBeInTheDocument();
    expect(screen.getByText("today")).toBeInTheDocument();
    expect(screen.queryByText("https://fallback.example.local/only-url")).not.toBeInTheDocument();
  });

  it("falls back to raw sources when sourceDetails are absent", () => {
    render(
      <ChatMessageList
        isSending={false}
        messages={[
          {
            id: "assistant-2",
            role: "assistant",
            content: "Nguon URL thuan.",
            sources: ["https://fallback.example.local/only-url"],
          },
        ]}
      />,
    );

    expect(screen.getByText("https://fallback.example.local/only-url")).toBeInTheDocument();
  });
});
