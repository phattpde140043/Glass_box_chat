# Glass Box Chat — Project Specification

> For system architecture and data flow, see [Pipeline Architecture](pipeline-architecture.md).
> For agent execution logic, see [Agent Execution Flow](agent-execution.md).
> For product overview, see the [README](../README.md).
>
> This document covers scope, requirements, and evaluation criteria only.

---

## 1. Objective

Build an AI chat application that makes internal agent execution visible to the user in real time — including reasoning steps, tool calls, sub-agent orchestration, and completion states — as a transparency and debugging layer on top of a standard chat interface.

---

## 2. Scope

### In scope

- Chat interface with streaming response
- Real-time trace visualization (reasoning, tool calls, sub-agent events)
- Agent runtime with tool calling and basic multi-step orchestration
- Session-scoped event history
- Event persistence for replay and review
- Human-in-the-loop pause and resume support
- Multi-provider LLM support (Claude, Gemini)

### Out of scope

- User authentication and authorization
- Persistent memory across sessions
- Multi-user collaboration
- Horizontal scaling or distributed runtime
- Production-grade infrastructure (the demo runs on free-tier hosting)
- Mobile interface

---

## 3. Functional Requirements

### 3.1 Chat

| # | Requirement |
|---|---|
| F1 | User can send a text message and receive a response |
| F2 | Response must be streamed incrementally, not delivered all at once |
| F3 | Conversation must be session-aware across multiple turns |
| F4 | Each message turn is independently traceable |

### 3.2 Transparency Layer

| # | Requirement |
|---|---|
| F5 | Each significant agent action must emit a typed, ordered event |
| F6 | Events must include: type, agent, detail, timestamp, session scope, message scope |
| F7 | The UI must render events as a live trace view while the run is in progress |
| F8 | The trace must surface at minimum: `thinking`, `tool_call`, `tool_result`, sub-agent events, and `done` |
| F9 | The trace must update in real time without requiring a page reload |

### 3.3 Agent Runtime

| # | Requirement |
|---|---|
| F10 | The agent must be able to call at least one external or internal tool |
| F11 | The agent must support a basic multi-step execution model (sequential or parallel) |
| F12 | Sub-agent activity must be emitted as discrete events visible in the trace |
| F13 | The runtime must support at least one real LLM provider (Claude or Gemini) |
| F14 | The system must fall back gracefully if no LLM key is configured |

### 3.4 Session and Event History

| # | Requirement |
|---|---|
| F15 | Events must be persisted for the duration of a session |
| F16 | Past session events must be queryable via API |
| F17 | The event history must be sufficient to reconstruct a full run after it ends |

---

## 4. Non-Functional Requirements

| # | Requirement |
|---|---|
| N1 | Event ordering must be preserved end-to-end (emission → transport → UI) |
| N2 | The UI must remain responsive while the agent is running — no blocking renders |
| N3 | Errors must be surfaced to the user, not silently swallowed |
| N4 | The system must handle stream disconnection without corrupting session state |
| N5 | The backend must not block the HTTP request handler during long-running agent execution |
| N6 | The streaming transport must be inspectable and debuggable (SSE over WebSocket for this reason) |

---

## 5. Design Constraints

These constraints are fixed decisions that define the system boundary. Implementation details are covered in the architecture documents.

| Constraint | Rationale |
|---|---|
| Event-driven execution model | Every state change must be observable; no hidden transitions |
| SSE as the streaming transport | Simple, unidirectional, inspectable — fits the server-to-client flow |
| Intermediate steps must be exposed | This is the core product value; a system that hides reasoning does not meet the objective |
| Shared type contracts across frontend and backend | Prevents schema drift between the event producer and consumer |
| Monorepo structure | SDK, runtime, types, and frontend evolve together and must stay aligned |

---

## 6. Evaluation Criteria

### 6.1 Transparency

- Can the user observe intermediate steps while the agent is running?
- Are tool calls and tool results visible in the trace?
- Is the trace structured and readable, not just a raw log dump?

### 6.2 System Design

- Is there a clear separation between the UI layer, the API proxy, the backend runtime, and the agent SDK?
- Is the streaming architecture correctly designed — decoupled intake, event-driven execution, ordered delivery?
- Are shared contracts enforced at package boundaries?

### 6.3 AI Fluency

- Are LLM APIs integrated correctly, including streaming and error handling?
- Does the system demonstrate awareness of LLM limitations (hallucination, latency, fallback)?
- Is tool calling implemented in a way that is visible and auditable?

### 6.4 Code Quality

- Is the codebase structured with clear module responsibilities?
- Is the business logic separated from transport and persistence concerns?
- Is the code readable without requiring deep familiarity with the project?

### 6.5 Engineering Maturity

- Are non-functional requirements treated explicitly (ordering, error surfacing, non-blocking execution)?
- Are there tests covering critical paths?
- Is the system deployable end-to-end with clear environment setup?

### 6.6 Communication

- Does the README convey the product clearly to someone unfamiliar with the project?
- Do the design documents explain the system at the right level of depth?
- Is scope explicitly defined so the reader knows what is and is not included?

---

## 7. Deliverables

| Deliverable | Location |
|---|---|
| Source code | GitHub repository |
| Product overview | [README](../README.md) |
| Pipeline architecture | [docs/pipeline-architecture.md](pipeline-architecture.md) |
| Agent execution model | [docs/agent-execution.md](agent-execution.md) |
| This specification | [docs/spec.md](spec.md) |
| Live demo | [glass-box-chat-web.vercel.app](https://glass-box-chat-web.vercel.app/) |
| Video walkthrough | [Loom demo](https://www.loom.com/share/24eb38787dc644e089c1dd5a957eaee1) |
| Backend tests | `pytest` at repo root |
| Frontend tests | `pnpm --filter web test` |

---

## 8. Optional Extensions

These were not required but were considered during design:

| Extension | Status |
|---|---|
| RAG / retrieval-augmented generation | Not implemented |
| Persistent memory across sessions | Not implemented |
| Visual DAG graph for multi-agent runs | Not implemented |
| Shareable trace links | Not implemented |
| Multi-user support | Not implemented |
| Deployed public demo | ✅ Implemented (free tier) |
