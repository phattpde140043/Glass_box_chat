"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent, type UIEvent } from "react";
import { runChatStream } from "../actions/chat-stream-action";
import { traceStorage } from "../lib/trace-storage";
import { ChatMessageModel, initialAssistantMessage } from "../models/chat-message";
import { RunChatRequestModel } from "../models/chat-run-request";
import { INITIAL_TRACE_WINDOW, TRACE_WINDOW_STEP, TraceEventModel } from "../models/trace-event";
import type { RuntimeMetrics } from "../models/runtime-metrics";
import { loadRuntimeHistory, loadRuntimeMetrics } from "../services/runtime-history";
import { useTraceStore } from "../store/trace-store";
import type { AgentStatus, ChatMessageRecord, TraceEventRecord } from "../validation/chat-schemas";

const INPUT_MAX_LENGTH = 2000;

function buildRequestFailureMessage(error: unknown): string {
  if (error instanceof Error) {
    return `Failed to send the request to the backend. Error: ${error.message}. Please verify the API is running on port 8000.`;
  }

  return "Failed to send the request to the backend. Please verify the API is running on port 8000.";
}

function mergeTraceEvents(...eventGroups: TraceEventRecord[][]): TraceEventRecord[] {
  const seen = new Set<string>();
  const merged: Array<{ event: TraceEventRecord; index: number }> = [];
  let sequence = 0;

  for (const events of eventGroups) {
    for (const event of events) {
      if (seen.has(event.id)) {
        continue;
      }

      seen.add(event.id);
      merged.push({ event, index: sequence });
      sequence += 1;
    }
  }

  const parseTime = (value: string): number | null => {
    const normalized = value.trim();
    const match = normalized.match(/(\d{1,2}):(\d{2}):(\d{2})(?:\s*(AM|PM))?/i);
    if (!match) {
      return null;
    }

    let hour = Number(match[1]);
    const minute = Number(match[2]);
    const second = Number(match[3]);

    if (Number.isNaN(hour) || Number.isNaN(minute) || Number.isNaN(second)) {
      return null;
    }

    const meridiem = match[4]?.toUpperCase();
    if (meridiem === "AM" && hour === 12) {
      hour = 0;
    }
    if (meridiem === "PM" && hour < 12) {
      hour += 12;
    }

    return hour * 3600 + minute * 60 + second;
  };

  merged.sort((left, right) => {
    const leftTime = parseTime(left.event.createdAt);
    const rightTime = parseTime(right.event.createdAt);

    if (leftTime !== null && rightTime !== null && leftTime !== rightTime) {
      return leftTime - rightTime;
    }

    return left.index - right.index;
  });

  return merged.map(({ event }) => event);
}

export function useChatRuntime() {
  const traceListRef = useRef<HTMLDivElement | null>(null);
  const [messages, setMessages] = useState<ChatMessageRecord[]>([initialAssistantMessage]);
  const [inputValue, setInputValue] = useState("");
  const [inputError, setInputError] = useState<string | null>(RunChatRequestModel.getValidationMessage(""));
  const [isSending, setIsSending] = useState(false);
  const [agentStatus, setAgentStatus] = useState<AgentStatus>("done");

  const {
    appendTraceEvent,
    expandedSessions,
    expandedSupportingEvents,
    hasHydratedTrace,
    hydrateTrace: hydrateTraceState,
    resetSessionExpansionsForSession,
    setHasHydratedTrace,
    setRuntimeMetrics,
    setShouldStickToBottom,
    setShowScrollToLatest,
    setVisibleTraceCount,
    runtimeMetrics,
    shouldStickToBottom,
    showScrollToLatest,
    toggleSession,
    toggleSupportingEvents,
    traceEvents,
    visibleTraceCount,
  } = useTraceStore();

  const groupedVisibleTraceSessions = useMemo(
    () => TraceEventModel.groupVisible(traceEvents, visibleTraceCount),
    [traceEvents, visibleTraceCount],
  );
  const hiddenTraceCount = Math.max(0, traceEvents.length - visibleTraceCount);
  const canSend = useMemo(
    () => inputValue.trim().length > 0 && !isSending && !inputError,
    [inputError, inputValue, isSending],
  );

  useEffect(() => {
    let isMounted = true;

    const hydrateTraceFromDb = async () => {
      let backendEvents = [] as typeof traceEvents;
      let persistedEvents = [] as typeof traceEvents;
      let metrics = null as RuntimeMetrics | null;

      try {
        backendEvents = await loadRuntimeHistory();
      } catch {
        backendEvents = [];
      }

      try {
        metrics = await loadRuntimeMetrics();
      } catch {
        metrics = null;
      }

      try {
        persistedEvents = await traceStorage.load();
        if (!isMounted) {
          return;
        }

        const mergedEvents = mergeTraceEvents(backendEvents, persistedEvents);
        hydrateTraceState(mergedEvents);
        if (metrics) {
          setRuntimeMetrics(metrics);
        }
      } catch {
        if (isMounted) {
          hydrateTraceState(backendEvents);
          if (metrics) {
            setRuntimeMetrics(metrics);
          }
        }
      } finally {
        if (isMounted) {
          setHasHydratedTrace(true);
        }
      }
    };

    void hydrateTraceFromDb();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (!hasHydratedTrace) {
      return;
    }

    void traceStorage.save(traceEvents);
  }, [hasHydratedTrace, traceEvents]);

  useEffect(() => {
    if (!hasHydratedTrace) {
      return;
    }

    const element = traceListRef.current;
    if (!element) {
      return;
    }

    if (shouldStickToBottom) {
      element.scrollTo({
        top: element.scrollHeight,
        behavior: traceEvents.length <= 1 ? "auto" : "smooth",
      });
      setShouldStickToBottom(true);
      setShowScrollToLatest(false);
      return;
    }

    const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    const isNearBottom = distanceFromBottom <= 48;
    setShouldStickToBottom(isNearBottom);
    setShowScrollToLatest(!isNearBottom);
  }, [groupedVisibleTraceSessions, hasHydratedTrace, shouldStickToBottom, traceEvents.length]);

  const handleInputChange = (value: string) => {
    setInputValue(value);
    setInputError(RunChatRequestModel.getValidationMessage(value));
  };

  const handleTraceScroll = (event: UIEvent<HTMLDivElement>) => {
    const element = event.currentTarget;
    const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    const isNearBottom = distanceFromBottom <= 48;
    setShouldStickToBottom(isNearBottom);
    setShowScrollToLatest(!isNearBottom);

    if (element.scrollTop <= 24 && hiddenTraceCount > 0) {
      setVisibleTraceCount((previousCount: number) => Math.min(traceEvents.length, previousCount + TRACE_WINDOW_STEP));
    }
  };

  const scrollTraceToBottom = () => {
    const element = traceListRef.current;
    if (!element) {
      return;
    }

    element.scrollTo({
      top: element.scrollHeight,
      behavior: "smooth",
    });
    setShouldStickToBottom(true);
    setShowScrollToLatest(false);
  };

  const sendMessage = async (text: string) => {
    if (isSending) {
      return;
    }

    const validationMessage = RunChatRequestModel.getValidationMessage(text);
    setInputError(validationMessage);
    if (validationMessage) {
      return;
    }

    const request = RunChatRequestModel.fromPrompt(text);
    const userMessage = ChatMessageModel.user(request.prompt).toJSON();

    setMessages((previousMessages) => [...previousMessages, userMessage]);
    setVisibleTraceCount(INITIAL_TRACE_WINDOW);
    useTraceStore.setState({ expandedSupportingEvents: {} });
    setAgentStatus("running");
    setInputValue("");
    setInputError(RunChatRequestModel.getValidationMessage(""));
    setIsSending(true);

    try {
      await runChatStream(request.prompt, {
        onAssistantMessage: (content) => {
          setMessages((previousMessages) => [...previousMessages, ChatMessageModel.assistant(content).toJSON()]);
        },
        onTraceEvent: (event) => {
          appendTraceEvent(event);
          resetSessionExpansionsForSession(event.sessionId);
        },
      });

      setAgentStatus("done");
    } catch (error) {
      setMessages((previousMessages) => [
        ...previousMessages,
        ChatMessageModel.assistant(buildRequestFailureMessage(error), `assistant-error-${crypto.randomUUID()}`).toJSON(),
      ]);
      setAgentStatus("waiting_user");
    } finally {
      setIsSending(false);
    }
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await sendMessage(inputValue);
  };

  const handleKeyDown = async (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      await sendMessage(inputValue);
    }
  };

  return {
    agentStatus,
    canSend,
    expandedSessions,
    expandedSupportingEvents,
    groupedVisibleTraceSessions,
    handleInputChange,
    handleKeyDown,
    handleSubmit,
    handleTraceScroll,
    hiddenTraceCount,
    inputError,
    inputMaxLength: INPUT_MAX_LENGTH,
    inputValue,
    isSending,
    messages,
    scrollTraceToBottom,
    setVisibleTraceCount,
    showScrollToLatest,
    runtimeMetrics,
    toggleSession,
    toggleSupportingEvents,
    traceEvents,
    traceListRef,
  };
}
