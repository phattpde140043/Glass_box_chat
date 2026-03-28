"use client";

import { ChatHeader } from "./chat-header";
import { ChatInputForm } from "./chat-input-form";
import { ChatMessageList } from "./chat-message-list";
import { TracePanel } from "./trace-panel";
import { useChatRuntime } from "../hooks/use-chat-runtime";

export function ChatShell() {
  const chatRuntime = useChatRuntime();

  return (
    <main className="chat-page">
      <section className="chat-shell">
        <ChatHeader agentStatus={chatRuntime.agentStatus} />

        <div className="chat-body">
          <ChatMessageList isSending={chatRuntime.isSending} messages={chatRuntime.messages} />

          <TracePanel
            expandedSessions={chatRuntime.expandedSessions}
            expandedSupportingEvents={chatRuntime.expandedSupportingEvents}
            groupedVisibleTraceSessions={chatRuntime.groupedVisibleTraceSessions}
            hiddenTraceCount={chatRuntime.hiddenTraceCount}
            onScroll={chatRuntime.handleTraceScroll}
            onScrollToLatest={chatRuntime.scrollTraceToBottom}
            onToggleSession={chatRuntime.toggleSession}
            onToggleSupportingEvents={chatRuntime.toggleSupportingEvents}
            runtimeMetrics={chatRuntime.runtimeMetrics}
            setVisibleTraceCount={chatRuntime.setVisibleTraceCount}
            showScrollToLatest={chatRuntime.showScrollToLatest}
            totalTraceCount={chatRuntime.traceEvents.length}
            traceListRef={chatRuntime.traceListRef}
          />
        </div>

        <ChatInputForm
          canSend={chatRuntime.canSend}
          currentLength={chatRuntime.inputValue.length}
          inputError={chatRuntime.inputError}
          isSending={chatRuntime.isSending}
          maxLength={chatRuntime.inputMaxLength}
          onChange={chatRuntime.handleInputChange}
          onKeyDown={chatRuntime.handleKeyDown}
          onSubmit={chatRuntime.handleSubmit}
          value={chatRuntime.inputValue}
        />
      </section>
    </main>
  );
}
