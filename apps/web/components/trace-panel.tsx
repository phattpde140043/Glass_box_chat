import type { RefObject, UIEvent } from "react";
import type { RuntimeMetrics } from "../models/runtime-metrics";
import { TraceEventModel, TRACE_WINDOW_STEP, type TraceSessionSection } from "../models/trace-event";

type TracePanelProps = {
  expandedSessions: Record<string, boolean>;
  expandedSupportingEvents: Record<string, boolean>;
  groupedVisibleTraceSessions: TraceSessionSection[];
  hiddenTraceCount: number;
  onScroll: (event: UIEvent<HTMLDivElement>) => void;
  onScrollToLatest: () => void;
  onToggleSession: (sessionId: string) => void;
  onToggleSupportingEvents: (sessionId: string) => void;
  runtimeMetrics: RuntimeMetrics;
  setVisibleTraceCount: (updater: (previousCount: number) => number) => void;
  showScrollToLatest: boolean;
  totalTraceCount: number;
  traceListRef: RefObject<HTMLDivElement | null>;
};

export function TracePanel({
  expandedSessions,
  expandedSupportingEvents,
  groupedVisibleTraceSessions,
  hiddenTraceCount,
  onScroll,
  onScrollToLatest,
  onToggleSession,
  onToggleSupportingEvents,
  runtimeMetrics,
  setVisibleTraceCount,
  showScrollToLatest,
  totalTraceCount,
  traceListRef,
}: TracePanelProps) {
  return (
    <aside className="trace-panel" aria-label="Runtime trace panel">
      <h2>Runtime Trace</h2>
      <div className="trace-list" onScroll={onScroll} ref={traceListRef}>
        <section className="trace-metrics-grid" aria-label="Runtime metrics summary">
          <article className="trace-metric-card accent">
            <span className="trace-metric-label">Runs</span>
            <strong>{runtimeMetrics.total_runs}</strong>
            <span className="trace-metric-caption">Last DAG: {runtimeMetrics.last_dag_node_count} nodes</span>
          </article>
          <article className="trace-metric-card">
            <span className="trace-metric-label">Executor</span>
            <strong>{runtimeMetrics.avg_node_duration_ms} ms</strong>
            <span className="trace-metric-caption">Avg node duration</span>
          </article>
          <article className="trace-metric-card">
            <span className="trace-metric-label">Cache</span>
            <strong>{runtimeMetrics.cache_hits}</strong>
            <span className="trace-metric-caption">Hits / {runtimeMetrics.cache_misses} misses</span>
          </article>
          <article className="trace-metric-card">
            <span className="trace-metric-label">Resilience</span>
            <strong>{runtimeMetrics.retries}</strong>
            <span className="trace-metric-caption">Retries, {runtimeMetrics.timeouts} timeouts</span>
          </article>
        </section>

        <section className="trace-breaker-strip" aria-label="Circuit breaker status">
          <span className="trace-breaker-title">Breaker</span>
          {Object.keys(runtimeMetrics.breaker_states).length === 0 ? (
            <span className="trace-breaker-badge closed">No trips</span>
          ) : (
            Object.entries(runtimeMetrics.breaker_states).map(([skill, isOpen]) => (
              <span key={skill} className={`trace-breaker-badge ${isOpen ? "open" : "closed"}`}>
                {skill}: {isOpen ? "open" : "closed"}
              </span>
            ))
          )}
          <span className="trace-breaker-timestamp">Last complete: {runtimeMetrics.last_completed_at ?? "n/a"}</span>
        </section>

        {hiddenTraceCount > 0 ? (
          <button
            type="button"
            className="trace-load-more"
            onClick={() => setVisibleTraceCount((previousCount) => Math.min(totalTraceCount, previousCount + TRACE_WINDOW_STEP))}
          >
            Load {Math.min(hiddenTraceCount, TRACE_WINDOW_STEP)} older events
          </button>
        ) : null}

        {groupedVisibleTraceSessions.length === 0 ? (
          <div className="trace-session-collapsed">No trace events for this session yet.</div>
        ) : null}

        {groupedVisibleTraceSessions.map((section) => {
          const isExpanded = expandedSessions[section.sessionId] ?? section.sessionId !== "system";

          return (
            <section key={section.sessionId} className="trace-session">
              <button type="button" className="trace-session-toggle" onClick={() => onToggleSession(section.sessionId)}>
                <span>{section.sessionLabel}</span>
                <span>{section.events.length} events</span>
                <span>{isExpanded ? "Hide" : "Show"}</span>
              </button>

              {isExpanded ? (
                <div className="trace-session-events">
                  {(() => {
                    const { primary, supporting } = TraceEventModel.splitPrimaryAndSupporting(section.events);
                    const showSupporting = expandedSupportingEvents[section.sessionId] ?? false;
                    const renderedEvents = showSupporting ? section.events : primary;

                    return (
                      <>
                        {supporting.length > 0 ? (
                          <button
                            type="button"
                            className="trace-supporting-toggle"
                            onClick={() => onToggleSupportingEvents(section.sessionId)}
                          >
                            <span>{showSupporting ? "Hide" : "Show"} supporting events</span>
                            <span>{supporting.length} supporting events</span>
                          </button>
                        ) : null}

                        {renderedEvents.map((event) => (
                          (() => {
                            const dag = parseDagDetail(event.detail);
                            return (
                              <article key={event.id} className={`trace-item branch-${event.branch} event-${event.event}`}>
                                <div className={`trace-lane branch-${event.branch}`} aria-hidden="true">
                                  <span className="trace-lane-line" />
                                  <span className="trace-lane-dot" />
                                </div>
                                <div className="trace-content">
                                  <header className="trace-header-row">
                                    <span className={`trace-tag ${event.event}`}>Event: {event.event}</span>
                                    <span className="trace-meta">{event.agent}</span>
                                    <span className="trace-meta">Branch {event.branch}</span>
                                    <span className="trace-meta">{event.mode}</span>
                                    <time className="trace-time">{event.createdAt}</time>
                                  </header>

                                  {(dag.nodeId || dag.skill || dag.deps || dag.score || dag.durationMs || dag.attempts) ? (
                                    <div className="trace-dag-badges">
                                      {dag.nodeId ? <span className="trace-chip">Node {dag.nodeId}</span> : null}
                                      {dag.skill ? <span className="trace-chip">Skill {dag.skill}</span> : null}
                                      {dag.deps ? <span className="trace-chip">Deps {dag.deps}</span> : null}
                                      {dag.score ? <span className="trace-chip emphasis">Score {dag.score}</span> : null}
                                      {dag.cacheHit ? <span className="trace-chip">Cache {dag.cacheHit}</span> : null}
                                      {dag.durationMs ? <span className="trace-chip">{dag.durationMs} ms</span> : null}
                                      {dag.attempts ? <span className="trace-chip">Attempt {dag.attempts}</span> : null}
                                      {dag.success ? <span className={`trace-chip ${dag.success === "true" ? "ok" : "warn"}`}>Success {dag.success}</span> : null}
                                    </div>
                                  ) : null}

                                  <p className="trace-detail">
                                    <strong>Detail:</strong> {event.detail}
                                  </p>
                                </div>
                              </article>
                            );
                          })()
                        ))}
                      </>
                    );
                  })()}
                </div>
              ) : (
                <div className="trace-session-collapsed">This session is collapsed to keep the trace panel compact.</div>
              )}
            </section>
          );
        })}
      </div>

      {showScrollToLatest ? (
        <button
          type="button"
          className="trace-scroll-latest"
          onClick={onScrollToLatest}
          aria-label="Scroll to latest event"
          title="Scroll to latest event"
        >
          ↓
        </button>
      ) : null}
    </aside>
  );
}

type ParsedDagDetail = {
  nodeId?: string;
  skill?: string;
  deps?: string;
  score?: string;
  cacheHit?: string;
  durationMs?: string;
  attempts?: string;
  success?: string;
};

function parseDagDetail(detail: string): ParsedDagDetail {
  const read = (label: string) => detail.match(new RegExp(`${label}=([^\\s]+)`))?.[1];
  return {
    nodeId: read("node") ?? read("node_id"),
    skill: read("skill"),
    deps: read("deps"),
    score: read("score"),
    cacheHit: read("cache_hit"),
    durationMs: read("duration_ms"),
    attempts: read("attempts"),
    success: read("success"),
  };
}
