import { create } from "zustand";
import { INITIAL_TRACE_WINDOW, TraceEventModel } from "../models/trace-event";
import type { TraceEventRecord } from "../validation/chat-schemas";

type TraceState = {
  expandedSessions: Record<string, boolean>;
  expandedSupportingEvents: Record<string, boolean>;
  hasHydratedTrace: boolean;
  shouldStickToBottom: boolean;
  showScrollToLatest: boolean;
  traceEvents: TraceEventRecord[];
  visibleTraceCount: number;
};

type TraceActions = {
  appendTraceEvent: (event: TraceEventRecord) => void;
  hydrateTrace: (events: TraceEventRecord[]) => void;
  resetSessionExpansionsForSession: (sessionId: string) => void;
  setHasHydratedTrace: (value: boolean) => void;
  setShouldStickToBottom: (value: boolean) => void;
  setShowScrollToLatest: (value: boolean) => void;
  setVisibleTraceCount: (updater: ((previous: number) => number) | number) => void;
  toggleSession: (sessionId: string) => void;
  toggleSupportingEvents: (sessionId: string) => void;
};

type TraceStore = TraceState & TraceActions;

const bootstrapTrace = TraceEventModel.bootstrap();

export const useTraceStore = create<TraceStore>((set) => ({
  expandedSessions: { system: true },
  expandedSupportingEvents: {},
  hasHydratedTrace: false,
  shouldStickToBottom: true,
  showScrollToLatest: false,
  traceEvents: [bootstrapTrace],
  visibleTraceCount: INITIAL_TRACE_WINDOW,

  appendTraceEvent: (event) =>
    set((state) => ({
      traceEvents: [...state.traceEvents, event],
    })),

  hydrateTrace: (events) =>
    set(() => {
      if (events.length === 0) {
        return {
          expandedSessions: { system: true },
          traceEvents: [bootstrapTrace],
        };
      }

      const latestSessionId = events[events.length - 1]?.sessionId ?? "system";
      return {
        expandedSessions: {
          system: latestSessionId === "system",
          [latestSessionId]: true,
        },
        traceEvents: events,
      };
    }),

  resetSessionExpansionsForSession: (sessionId) =>
    set((state) => ({
      expandedSessions: {
        ...Object.fromEntries(Object.keys(state.expandedSessions).map((key) => [key, false])),
        [sessionId]: true,
      },
    })),

  setHasHydratedTrace: (value) => set(() => ({ hasHydratedTrace: value })),
  setShouldStickToBottom: (value) => set(() => ({ shouldStickToBottom: value })),
  setShowScrollToLatest: (value) => set(() => ({ showScrollToLatest: value })),

  setVisibleTraceCount: (updater) =>
    set((state) => ({
      visibleTraceCount: typeof updater === "function" ? updater(state.visibleTraceCount) : updater,
    })),

  toggleSession: (sessionId) =>
    set((state) => ({
      expandedSessions: {
        ...state.expandedSessions,
        [sessionId]: !state.expandedSessions[sessionId],
      },
    })),

  toggleSupportingEvents: (sessionId) =>
    set((state) => ({
      expandedSupportingEvents: {
        ...state.expandedSupportingEvents,
        [sessionId]: !state.expandedSupportingEvents[sessionId],
      },
    })),
}));
