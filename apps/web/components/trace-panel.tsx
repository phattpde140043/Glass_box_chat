import type { RefObject, UIEvent } from "react";
import type { RuntimeMetrics } from "../models/runtime-metrics";
import { TraceEventModel, TRACE_WINDOW_STEP, type TraceSessionGroupedByMessage, type TraceMessageSection } from "../models/trace-event";
import type { TraceEventRecord, TraceEventType } from "@glassbox/types";

type TracePanelProps = {
  expandedSessions: Record<string, boolean>;
  expandedSupportingEvents: Record<string, boolean>;
  groupedVisibleTraceSessions: TraceSessionGroupedByMessage[];
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
          <div className="trace-session-collapsed">No trace events for the current session yet.</div>
        ) : null}

        {groupedVisibleTraceSessions.map((section) => {
          const totalEvents = section.messages.reduce((sum: number, msg: TraceMessageSection) => sum + msg.events.length, 0);

          return (
            <section key={section.sessionId} className="trace-session">
              <div className="trace-session-toggle" role="group" aria-label={`Session ${section.sessionId}`}>
                <span>{section.sessionLabel}</span>
                <span>{totalEvents} events</span>
                <span>{section.messages.length} messages</span>
              </div>

              <div className="trace-session-events">
                {section.messages.length === 0 ? (
                  <div className="trace-session-collapsed">No trace events for this session.</div>
                ) : (
                  section.messages.map((message: TraceMessageSection) => {
                    const messageSectionKey = `${section.sessionId}:${message.messageId}`;
                    const isMessageExpanded = expandedSessions[messageSectionKey] ?? true;

                    return (
                      <section key={message.messageId} className="trace-message-group">
                        <button
                          type="button"
                          className="trace-message-toggle"
                          onClick={() => onToggleSession(messageSectionKey)}
                        >
                          <span>Message {message.messageId.substring(0, 8)}</span>
                          <span>{message.events.length} events</span>
                          <span>{isMessageExpanded ? "Hide" : "Show"}</span>
                        </button>

                        {isMessageExpanded ? (
                          <div className="trace-message-events">
                            {(() => {
                              const artifacts = collectArtifacts(message.events);
                              const baseTime = message.events[0]?.createdAt ?? "";
                              const { primary, supporting } = TraceEventModel.splitPrimaryAndSupporting(message.events);
                              const showSupporting = expandedSupportingEvents[message.messageId] ?? false;
                              const renderedEvents = showSupporting ? message.events : primary;

                              return (
                                <>
                                  {artifacts.length > 0 ? (
                                    <section className="trace-artifact-section" aria-label="Generated artifacts">
                                      <header>
                                        <strong>Artifacts</strong>
                                        <span>{artifacts.length} item(s)</span>
                                      </header>
                                      <div className="trace-artifact-list">
                                        {artifacts.map((artifact) => (
                                          <article key={artifact.id} className={`trace-artifact status-${artifact.status}`}>
                                            <div className="trace-artifact-title">{artifact.title}</div>
                                            <div className="trace-artifact-meta">
                                              <span>Type: {artifact.type}</span>
                                              <span>Status: {artifact.status}</span>
                                              <span>{artifact.createdAt}</span>
                                            </div>
                                            {artifact.content ? <p className="trace-artifact-content">{artifact.content}</p> : null}
                                            {artifact.url ? (
                                              <a className="trace-citation-link" href={artifact.url} target="_blank" rel="noreferrer">
                                                {artifact.url}
                                              </a>
                                            ) : null}
                                          </article>
                                        ))}
                                      </div>
                                    </section>
                                  ) : null}

                                  <PhaseProgressBar events={message.events} />
                                  <PipelineFlowDiagram events={message.events} />

                                  {supporting.length > 0 ? (
                                    <button
                                      type="button"
                                      className="trace-supporting-toggle"
                                      onClick={() => onToggleSupportingEvents(message.messageId)}
                                    >
                                      <span>{showSupporting ? "Hide" : "Show"} supporting events</span>
                                      <span>{supporting.length} supporting events</span>
                                    </button>
                                  ) : null}

                                  {renderedEvents.map((event: TraceEventRecord) => (
                                    (() => {
                                      const dag = parseDagDetail(event);
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
                                              {baseTime ? <span className="trace-relative-time">{relativeTimeSecs(baseTime, event.createdAt)}</span> : null}
                                            </header>

                                            {(dag.nodeId || dag.skill || dag.deps || dag.score || dag.durationMs || dag.attempts || dag.provider) ? (
                                              <div className="trace-dag-badges">
                                                {dag.nodeId ? <span className="trace-chip">Node {dag.nodeId}</span> : null}
                                                {dag.skill ? <span className="trace-chip">Skill {dag.skill}</span> : null}
                                                {dag.deps ? <span className="trace-chip">Deps {dag.deps}</span> : null}
                                                {dag.score ? <span className="trace-chip emphasis">Score {dag.score}</span> : null}
                                                {dag.provider ? <span className="trace-chip">Provider {dag.provider}</span> : null}
                                                {dag.freshness ? <span className="trace-chip">Freshness {dag.freshness}</span> : null}
                                                {dag.sourceCount ? <span className="trace-chip">Sources {dag.sourceCount}</span> : null}
                                                {dag.citationCount ? <span className="trace-chip">Citations {dag.citationCount}</span> : null}
                                                {dag.fallbackUsed === "true" ? <span className="trace-chip warn">Fallback search</span> : null}
                                                {dag.cacheHit ? <span className="trace-chip">Cache {dag.cacheHit}</span> : null}
                                                {dag.durationMs ? <span className="trace-chip">{dag.durationMs} ms</span> : null}
                                                {dag.attempts ? <span className="trace-chip">Attempt {dag.attempts}</span> : null}
                                                {dag.success ? <span className={`trace-chip ${dag.success === "true" ? "ok" : "warn"}`}>Success {dag.success}</span> : null}
                                              </div>
                                            ) : null}

                                            {dag.citations && dag.citations.length > 0 ? (
                                              <div className="trace-citation-block">
                                                <strong>Sources:</strong>
                                                <div className="trace-citation-list">
                                                  {dag.citations.map((citation) => (
                                                    <a
                                                      key={citation}
                                                      className="trace-citation-link"
                                                      href={citation}
                                                      target="_blank"
                                                      rel="noreferrer"
                                                    >
                                                      {citation}
                                                    </a>
                                                  ))}
                                                </div>
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
                        ) : null}
                      </section>
                    );
                  })
                )}
              </div>
            </section>
          );
        })}
      </div>

      {showScrollToLatest ? (
        <button
          type="button"
          className="trace-scroll-latest"
          onClick={onScrollToLatest}
          aria-label="Scroll to the latest event"
          title="Scroll to the latest event"
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
  provider?: string;
  sourceCount?: string;
  citationCount?: string;
  freshness?: string;
  fallbackUsed?: string;
  cacheHit?: string;
  durationMs?: string;
  attempts?: string;
  success?: string;
  citations?: string[];
};

function parseDagDetail(event: TraceEventRecord): ParsedDagDetail {
  const metadata = event.metadata;
  if (metadata) {
    return {
      nodeId: metadata.nodeId,
      skill: metadata.skill,
      deps: metadata.deps?.join(","),
      score: metadata.score,
      provider: metadata.provider,
      sourceCount: metadata.sourceCount !== undefined ? String(metadata.sourceCount) : undefined,
      citationCount: metadata.citationCount !== undefined ? String(metadata.citationCount) : undefined,
      freshness: metadata.freshness,
      fallbackUsed: metadata.fallbackUsed !== undefined ? String(metadata.fallbackUsed) : undefined,
      cacheHit: metadata.cacheHit !== undefined ? String(metadata.cacheHit) : undefined,
      durationMs: metadata.durationMs !== undefined ? String(metadata.durationMs) : undefined,
      attempts: metadata.attempts !== undefined ? String(metadata.attempts) : undefined,
      success: metadata.success !== undefined ? String(metadata.success) : undefined,
      citations: metadata.citations,
    };
  }

  return parseDetailFallback(event.detail);
}

function parseDetailFallback(detail: string): ParsedDagDetail {
  const read = (label: string) => detail.match(new RegExp(`${label}=([^\\s]+)`))?.[1];
  const citationRaw = read("citations");
  return {
    nodeId: read("node") ?? read("node_id"),
    skill: read("skill"),
    deps: read("deps"),
    score: read("score"),
    provider: read("provider"),
    sourceCount: read("source_count"),
    citationCount: read("citation_count"),
    freshness: read("freshness"),
    fallbackUsed: read("fallback_used"),
    cacheHit: read("cache_hit"),
    durationMs: read("duration_ms"),
    attempts: read("attempts"),
    success: read("success"),
    citations: citationRaw && citationRaw !== "none" ? citationRaw.split(",").filter(Boolean) : undefined,
  };
}

function collectArtifacts(events: TraceEventRecord[]) {
  const seen = new Set<string>();
  const artifacts: NonNullable<TraceEventRecord["artifact"]>[] = [];
  for (const event of events) {
    if (!event.artifact) {
      continue;
    }
    if (seen.has(event.artifact.id)) {
      continue;
    }
    seen.add(event.artifact.id);
    artifacts.push(event.artifact);
  }
  return artifacts;
}

// ─── Timing helpers ──────────────────────────────────────────────────────────

function parseHms(hms: string): number {
  const parts = hms.split(":");
  if (parts.length !== 3) return 0;
  return Number(parts[0]) * 3600 + Number(parts[1]) * 60 + Number(parts[2]);
}

function relativeTimeSecs(base: string, current: string): string {
  const diff = parseHms(current) - parseHms(base);
  if (diff <= 0) return "+0s";
  if (diff < 60) return `+${diff}s`;
  return `+${Math.floor(diff / 60)}m${diff % 60}s`;
}

// ─── Phase Progress Bar ───────────────────────────────────────────────────────

type PhaseStep = { id: string; label: string; triggers: TraceEventType[] };

const PIPELINE_PHASES: PhaseStep[] = [
  { id: "analysis",  label: "Analysis",      triggers: ["thinking"] },
  { id: "planning",  label: "Planning",       triggers: ["node_start", "artifact_created"] },
  { id: "executing", label: "Executing",      triggers: ["subagent_start", "tool_call"] },
  { id: "synthesis", label: "Synthesis",      triggers: ["node_done", "tool_result", "subagent_done"] },
  { id: "done",      label: "Done",           triggers: ["done"] },
];

function PhaseProgressBar({ events }: { events: TraceEventRecord[] }) {
  const seenTypes = new Set(events.map((e) => e.event));

  let currentIndex = -1;
  for (let i = 0; i < PIPELINE_PHASES.length; i++) {
    if (PIPELINE_PHASES[i].triggers.some((t) => seenTypes.has(t))) {
      currentIndex = i;
    }
  }

  if (currentIndex < 0) return null;

  return (
    <div className="phase-progress-bar" aria-label="Execution phase progress">
      {PIPELINE_PHASES.map((phase, i) => {
        const isDone = i < currentIndex;
        const isActive = i === currentIndex;
        return (
          <div key={phase.id} className={`phase-step${isDone ? " done" : ""}${isActive ? " active" : ""}`}>
            <div className="phase-step-indicator">{isDone ? "✓" : i + 1}</div>
            <span className="phase-step-label">{phase.label}</span>
            {i < PIPELINE_PHASES.length - 1 ? (
              <div className={`phase-connector${isDone ? " done" : ""}`} aria-hidden="true" />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

// ─── Pipeline Flow Diagram ────────────────────────────────────────────────────

type NodeStatus = "pending" | "running" | "done" | "failed";

type DiagramNode = {
  nodeId: string;
  skill: string;
  deps: string[];
  branch: string;
  status: NodeStatus;
  durationMs?: number;
};

function buildDiagramNodes(events: TraceEventRecord[]): DiagramNode[] {
  const nodes = new Map<string, DiagramNode>();

  for (const event of events) {
    const meta = event.metadata;
    if (!meta?.nodeId) continue;

    if (event.event === "node_start") {
      if (!nodes.has(meta.nodeId)) {
        nodes.set(meta.nodeId, {
          nodeId: meta.nodeId,
          skill: meta.skill ?? "unknown",
          deps: meta.deps ?? [],
          branch: meta.branch ?? event.branch,
          status: "pending",
        });
      }
    }

    if (event.event === "subagent_start" && nodes.has(meta.nodeId)) {
      nodes.get(meta.nodeId)!.status = "running";
    }

    if (event.event === "node_done" && nodes.has(meta.nodeId)) {
      const node = nodes.get(meta.nodeId)!;
      node.status = meta.success === false ? "failed" : "done";
      if (meta.durationMs !== undefined) node.durationMs = meta.durationMs;
    }
  }

  return Array.from(nodes.values());
}

const NODE_STATUS_ICON: Record<NodeStatus, string> = {
  pending: "○",
  running: "⟳",
  done: "✓",
  failed: "✗",
};

function PipelineFlowDiagram({ events }: { events: TraceEventRecord[] }) {
  const nodes = buildDiagramNodes(events);
  if (nodes.length === 0) return null;

  const totalDuration = nodes.reduce((sum, n) => sum + (n.durationMs ?? 0), 0);

  return (
    <section className="pipeline-flow-diagram" aria-label="Execution pipeline flow">
      <header className="pipeline-flow-header">
        <strong>Pipeline Flow</strong>
        <span>{nodes.length} node{nodes.length !== 1 ? "s" : ""}</span>
        {totalDuration > 0 ? <span className="pipeline-total-duration">Total: {totalDuration} ms</span> : null}
      </header>
      <div className="pipeline-nodes">
        {nodes.map((node, i) => (
          <div key={node.nodeId} className="pipeline-node-wrapper">
            <div className={`pipeline-node node-status-${node.status}`}>
              <div className="pipeline-node-icon">{NODE_STATUS_ICON[node.status]}</div>
              <div className="pipeline-node-skill">{node.skill}</div>
              <div className="pipeline-node-id">{node.nodeId}</div>
              {node.durationMs !== undefined ? (
                <div className="pipeline-node-duration">{node.durationMs} ms</div>
              ) : null}
              {node.deps.length > 0 ? (
                <div className="pipeline-node-deps">← {node.deps.join(", ")}</div>
              ) : null}
            </div>
            {i < nodes.length - 1 ? <div className="pipeline-connector" aria-hidden="true">→</div> : null}
          </div>
        ))}
      </div>
    </section>
  );
}