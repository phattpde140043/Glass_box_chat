---
trigger: always_on
---

# System Architecture Overview

This is the canonical architecture document for The Glass Box.
The content below consolidates these previous files:
- system-design.instructions.md
- hybrid-architecture.instructions.md
- product-architecture.instructions.md
- backend-context.instructions.md

## Consolidated Content: System Design

# 🏗️ THE GLASS BOX — SYSTEM DESIGN (C4 MODEL + SEQUENCE DIAGRAM)

## 1. 🎯 Overview

This document describes the **system architecture and interaction flow** of The Glass Box system using:

- **C4 Model** (Context → Container → Component)
- **Sequence Diagrams** (runtime behavior)

# 🌍 2. C4 LEVEL 1 — SYSTEM CONTEXT

## 🎯 Goal

Define how the system interacts with external actors.

## 🧩 Diagram

```text
User (Developer / End-user)
        ↓
   Glass Box System
        ↓
 External Tools / LLM APIs
```

## 👥 Actors

### 1. User

- Interacts via UI
- Provides input (HITL)
- Observes agent execution

### 2. External Systems

- LLM APIs (optional)
- Tool APIs (search, DB, etc.)

## 💡 Key Insight

> The system acts as an **observable execution layer for AI agents**

# 🧱 3. C4 LEVEL 2 — CONTAINER DIAGRAM

## 🎯 Goal

Break system into deployable units

## 🧩 Diagram

```text
 ┌───────────────────────────────┐
 │        Frontend (Next.js)     │
 │  - Trace Tree UI              │
 │  - HITL Interaction           │
 └──────────────┬────────────────┘
                │ SSE / REST
 ┌──────────────▼────────────────┐
 │      Backend Server           │
 │  - API Layer (/run, /resume)  │
 │  - SSE Stream (/stream)       │
 └──────────────┬────────────────┘
                │
 ┌──────────────▼────────────────┐
 │     Agent Runtime Engine      │
 │  - Execution Orchestrator     │
 │  - Event Bus                  │
 └──────────────┬────────────────┘
                │
 ┌──────────────▼────────────────┐
 │         Agent SDK             │
 │  - Agent abstraction          │
 │  - Context API               │
 └──────────────┬────────────────┘
                │
 ┌──────────────▼────────────────┐
 │     Tools / LLM (Mocked)      │
 └───────────────────────────────┘
```

## 📦 Containers

### 3.1 Frontend

- React / Next.js
- Subscribes to event stream
- Renders execution tree

### 3.2 Backend API Layer

- Handles HTTP requests
- Bridges UI ↔ Runtime
- Exposes:

   - `/run`
   - `/resume`
   - `/stream`

### 3.3 Runtime Engine

- Core execution system
- Manages agents + lifecycle
- Emits events

### 3.4 Agent SDK

- Developer abstraction layer
- Defines agent behavior

### 3.5 Tools Layer

- External or mocked services

# 🧩 4. C4 LEVEL 3 — COMPONENT DIAGRAM (Backend)

## 🎯 Goal

Break runtime into internal components

## 🧩 Diagram

```text
Runtime Engine
 ├── Agent Manager
 │     ├── createAgent()
 │     ├── completeAgent()
 │
 ├── Context Factory
 │     ├── think()
 │     ├── tool()
 │     ├── spawn()
 │     ├── askUser()
 │
 ├── Event Bus
 │     ├── emit()
 │     ├── subscribe()
 │
 ├── HITL Manager
 │     ├── waitForUser()
 │     ├── resolveUser()
 │
 └── Execution Scheduler
       ├── async orchestration
       ├── parallel handling
```

## 🔍 Component Responsibilities

### Agent Manager

- Track agent lifecycle
- Assign IDs

### Context Factory

- Generate per-agent context
- Bind agentId to actions

### Event Bus

- Broadcast events to subscribers
- Decouple runtime & transport

### HITL Manager

- Store pending Promises
- Resume execution safely

### Execution Scheduler

- Handle async flows
- Enable parallel execution

# 🔄 5. SEQUENCE DIAGRAM — BASIC EXECUTION

## 🎯 Scenario: Run Agent

```text
User → Frontend → Backend → Runtime → Agent → Context → Event Bus → UI
```

## 🧩 Flow

```text
1. User clicks "Run"
2. Frontend calls POST /run
3. Backend initializes Runtime
4. Runtime executes Agent
5. Agent calls ctx.think()
6. Runtime emits event
7. SSE pushes event to UI
8. UI updates tree
```

# 🔄 6. SEQUENCE DIAGRAM — SUB-AGENT SPAWN

## 🎯 Scenario: Parallel Execution

```text
Parent Agent
   ↓
spawn(A)   spawn(B)
   ↓         ↓
Agent A   Agent B
```

## 🧩 Flow

```text
1. Agent calls ctx.spawn(A)
2. Runtime emits "spawn"
3. Runtime executes Agent A
4. Agent calls ctx.spawn(B)
5. Runtime emits "spawn"
6. Runtime executes Agent B
7. A and B run in parallel
8. Events interleave in stream
9. UI builds branching tree
```

# 🔄 7. SEQUENCE DIAGRAM — HITL (ask_user)

## 🎯 Scenario: Pause & Resume

## 🧩 Flow

```text
1. Agent calls ctx.askUser("Continue?")
2. Runtime emits "ask_user"
3. UI renders input box
4. Execution pauses (Promise pending)

--- WAIT STATE ---

5. User submits input
6. Frontend POST /resume
7. Backend resolves Promise
8. Agent resumes execution
9. Runtime emits new events
10. UI continues rendering
```

# 🔄 8. SEQUENCE DIAGRAM — STREAMING

## 🎯 Scenario: Real-time updates

## 🧩 Flow

```text
1. UI opens SSE connection (/stream)
2. Runtime emits event
3. Event Bus notifies subscribers
4. Server writes to SSE
5. UI receives event
6. UI updates state
```

# ⚠️ 9. Failure Scenarios

## 9.1 SSE Disconnect

```text
UI loses connection
 → reconnect
 → continue receiving events
```

## 9.2 Missing Events

- UI must be resilient
- State must be reconstructible

## 9.3 Unresolved HITL

- Timeout (optional)
- Manual cancel (future)

# 🚀 10. Scalability Considerations (Beyond MVP)

### Current (MVP)

- In-memory runtime
- Single instance

### Future

- Distributed event bus (Kafka)
- Persistent execution state
- Multi-session support
- WebSocket upgrade

# 💡 11. Key Architectural Insights

### Insight #1

> Runtime is the heart of the system

### Insight #2

> Event stream is the single source of truth

### Insight #3

> UI is a projection of runtime state

### Insight #4

> HITL is just async suspension

# 🏁 12. Summary

The Glass Box system is composed of:

- A **frontend observability UI**
- A **backend runtime engine**
- A **developer-facing SDK**

Together they form:

> 🔥 A transparent, event-driven AI agent execution platform

## Consolidated Content: Hybrid Architecture

# 🧬 THE GLASS BOX — HYBRID ARCHITECTURE SPECIFICATION

## (Task-based SDK + Event-driven Runtime)

## 1. 🎯 Purpose

This document defines the **baseline architecture** for The Glass Box system, combining:

- **Task-based orchestration (developer-facing SDK)**
- **Event-driven execution (runtime & infrastructure)**

It serves as:

- A **design contract** for implementing agents
- A **reference architecture** for scaling the system
- A **foundation for future distributed execution**

## 2. 🧠 Core Philosophy

> “Developers think in tasks. Systems scale with events.”

### 2.1 Dual Abstraction Model

| Layer   | Model        | Responsibility            |
| ------- | ------------ | ------------------------- |
| SDK     | Task-based   | Developer experience      |
| Runtime | Event-driven | Scalability & reliability |

## 3. 🧩 High-Level Architecture

```text
Agent (Task-based API)
        ↓
Runtime Adapter
        ↓
Task → Event Transformation
        ↓
Event Bus (Queue / Stream)
        ↓
Workers (Execution)
        ↓
Event Emission
        ↓
State Projection (UI)
```

## 4. 🔑 Core Concepts

### 4.1 Task

A **Task** represents an *intention to execute logic*.

```ts
type Task = {
  id: string;
  type: "agent" | "tool" | "hitl";
  payload: any;
  parentId?: string;
};
```

### 4.2 Event

An **Event** represents a *fact that has already happened*.

```ts
type Event = {
  id: string;
  type: string;
  agentId: string;
  payload: any;
  timestamp: number;
};
```

### 4.3 Key Difference

| Task    | Event     |
| ------- | --------- |
| Command | Fact      |
| Future  | Past      |
| Mutable | Immutable |

## 5. 🔄 Execution Model

### 5.1 Task Lifecycle

```text
Created → Scheduled → Executed → Completed
```

### 5.2 Event Lifecycle

```text
Emitted → Persisted → Streamed → Consumed
```

### 5.3 Mapping

| Task Action | Event       |
| ----------- | ----------- |
| start agent | agent_start |
| think       | thinking    |
| call tool   | tool_call   |
| spawn agent | spawn       |
| wait user   | ask_user    |
| complete    | done        |

## 6. ⚙️ Runtime Architecture

### 6.1 Components

```text
Runtime
 ├── Task Manager
 ├── Scheduler
 ├── Event Bus
 ├── State Store
 └── HITL Manager
```

### 6.2 Responsibilities

| Component    | Role                 |
| ------------ | -------------------- |
| Task Manager | create & track tasks |
| Scheduler    | dispatch tasks       |
| Event Bus    | distribute events    |
| State Store  | persist state        |
| HITL Manager | manage user input    |

## 7. 🔄 Task → Event Transformation

### 7.1 Flow

```text
ctx.spawn(A)
   ↓
Create Task
   ↓
Emit "task_created"
   ↓
Worker executes
   ↓
Emit execution events
```

### 7.2 Example

```ts
ctx.tool("search", input)
```

→ becomes:

```text
Task: tool_execution
Event: tool_call
Event: tool_result
```

## 8. ⚡ Concurrency Model

### 8.1 Task Parallelism

```ts
await Promise.all([
  ctx.spawn(A),
  ctx.spawn(B)
]);
```

### 8.2 Runtime Behavior

- Each task is independent
- Scheduled to workers
- Executed concurrently

### 8.3 Ordering Guarantees

- Per-agent ordering: optional
- Global ordering: NOT guaranteed

## 9. 🧍 Human-in-the-loop (HITL)

### 9.1 Task Representation

```ts
type HITLTask = {
  type: "hitl";
  agentId: string;
  question: string;
};
```

### 9.2 Flow

```text
Agent → askUser()
   ↓
Emit ask_user event
   ↓
Persist waiting state
   ↓
User responds
   ↓
Emit resume event
   ↓
Scheduler resumes task
```

### 9.3 Key Requirement

> HITL must be resumable across process restarts

## 10. 🌊 Event Bus Design

### 10.1 Requirements

- High throughput
- Durable
- Partitioned

### 10.2 Recommended

- Kafka (production)
- In-memory emitter (MVP)

### 10.3 Partitioning Strategy

```text
partition key = sessionId
```

## 11. 🗄️ State Management

### 11.1 Event Sourcing

- State derived from events

### 11.2 Projection

```text
Event stream → Agent Tree
```

### 11.3 Storage

| Data       | Store      |
| ---------- | ---------- |
| Events     | DB / Kafka |
| HITL state | Redis      |
| Sessions   | Postgres   |

## 12. 🔁 Failure & Recovery

### 12.1 Failure Cases

- Worker crash
- Network loss
- Partial execution

### 12.2 Recovery Strategy

```text
1. Reload events
2. Rebuild state
3. Resume pending tasks
```

### 12.3 Idempotency

- Task execution must be retry-safe

## 13. 🔐 Multi-Tenant Support

### 13.1 Context

```ts
type ExecutionContext = {
  tenantId: string;
  sessionId: string;
};
```

### 13.2 Isolation

- Partition events by tenant
- Namespace all keys

## 14. 📊 Observability

### 14.1 Event Logging

- Every action logged as event

### 14.2 Metrics

- task latency
- queue lag
- error rate

### 14.3 Tracing

- correlate via agentId / sessionId

## 15. 🚀 Scalability Model

### 15.1 Horizontal Scaling

- Stateless orchestrator
- Distributed workers

### 15.2 Load Distribution

```text
Queue → multiple workers
```

### 15.3 Bottlenecks

- queue throughput
- DB write speed
- UI rendering

## 16. ⚠️ Design Constraints

- No shared mutable state
- Event-first architecture
- Tasks must be retryable
- All state must be reconstructable

## 17. 💡 Key Insights

### Insight #1

> Task is for intent. Event is for truth.

### Insight #2

> Runtime is a state machine driven by events

### Insight #3

> UI is just a projection of events

## 18. 🏁 Summary

This hybrid architecture enables:

- Clean developer experience (task-based SDK)
- Strong scalability (event-driven runtime)
- Fault tolerance (event sourcing)
- Real-time observability (Glass Box UI)

## 19. 🔥 Final Statement

> This system is a **distributed, event-sourced agent execution platform with a task-based developer interface**

## Consolidated Content: Production Architecture

# 🚀 THE GLASS BOX — PRODUCTION-READY ARCHITECTURE

## 1. 🎯 Overview

This document extends the MVP architecture into a **production-ready system** capable of:

- Multi-tenant isolation
- Horizontal scaling
- Persistent execution state
- Fault tolerance & recovery
- High-throughput event streaming

## 2. 🧠 Design Goals

### 2.1 Multi-Tenancy

- Support multiple users/projects simultaneously
- Isolate execution contexts

### 2.2 Scalability

- Handle thousands of concurrent agents
- Horizontal scaling across instances

### 2.3 Reliability

- No data loss
- Recoverable execution state

### 2.4 Observability

- Full trace persistence
- Debuggable workflows

## 3. 🧱 High-Level Architecture (Production)

```text
                    ┌──────────────────────┐
                    │     Frontend UI      │
                    └──────────┬───────────┘
                               │
                     (WebSocket / SSE)
                               │
          ┌────────────────────▼────────────────────┐
          │            API Gateway / BFF            │
          └───────────────┬─────────────────────────┘
                          │
        ┌─────────────────▼──────────────────┐
        │        Orchestrator Service        │
        │  - Agent Runtime Instances         │
        │  - Execution Scheduler             │
        └───────────────┬────────────────────┘
                        │
        ┌───────────────▼────────────────────┐
        │         Message Queue (Kafka)      │
        │  - Event streaming                │
        │  - Decoupling                    │
        └───────────────┬────────────────────┘
                        │
        ┌───────────────▼────────────────────┐
        │         Worker Nodes               │
        │  - Execute agents                 │
        │  - Tool calls                     │
        └───────────────┬────────────────────┘
                        │
        ┌───────────────▼────────────────────┐
        │         Persistence Layer          │
        │  - DB (Postgres)                  │
        │  - Cache (Redis)                  │
        └────────────────────────────────────┘
```

## 4. 🧩 Multi-Tenant Architecture

### 4.1 Tenant Model

```ts
type Tenant = {
  id: string;
  name: string;
};
```

### 4.2 Isolation Strategy

| Layer   | Isolation                    |
| ------- | ---------------------------- |
| API     | Auth + tenantId              |
| Runtime | per-tenant execution context |
| DB      | tenant_id column             |
| Cache   | namespaced keys              |

### 4.3 Execution Context

```ts
type ExecutionContext = {
  tenantId: string;
  sessionId: string;
  runtimeId: string;
};
```

### 4.4 Key Insight

> Every event MUST include tenantId

## 5. ⚡ Scaling Strategy

### 5.1 Horizontal Scaling

- Multiple orchestrator instances
- Stateless API layer
- Shared queue

### 5.2 Worker Model

```text
Orchestrator → Queue → Workers
```

- Orchestrator schedules tasks
- Workers execute agents

### 5.3 Load Distribution

- Kafka partitions by `sessionId`
- Ensures ordering per session

### 5.4 Auto Scaling

- Scale workers based on queue lag
- Scale API based on request rate

## 6. 🗄️ Persistence Layer

### 6.1 What to Store?

| Data        | Purpose            |
| ----------- | ------------------ |
| Events      | replay & debugging |
| Agent state | resume execution   |
| Sessions    | user context       |

### 6.2 Event Store Schema

```ts
type EventRecord = {
  id: string;
  tenantId: string;
  sessionId: string;
  agentId: string;
  type: string;
  payload: any;
  timestamp: number;
};
```

### 6.3 Storage Strategy

- Append-only event log
- Indexed by sessionId

### 6.4 Database Choice

- Postgres → structured data
- S3 / Blob → large traces (optional)

## 7. 🔄 State Recovery

### 7.1 Problem

System crashes during execution

### 7.2 Solution: Event Replay

```text
1. Load events from DB
2. Rebuild agent tree
3. Resume from last state
```

### 7.3 Checkpointing (Optional)

- Snapshot state every N events
- Faster recovery

## 8. 🌊 Streaming Layer (Production)

### 8.1 WebSocket Upgrade

Replace SSE with WebSocket for:

- Bi-directional communication
- Lower latency
- Better scaling

### 8.2 Event Flow

```text
Runtime → Kafka → WebSocket Gateway → UI
```

### 8.3 Backpressure Handling

- Buffer events per client
- Drop or batch if overloaded

## 9. 🧍 HITL at Scale

### 9.1 Problem

Multiple users interacting concurrently

### 9.2 Solution

- Store pending inputs in Redis

```ts
key: "hitl:{agentId}"
value: { resolveToken }
```

### 9.3 Resume Flow

1. UI sends response
2. API writes to Redis
3. Worker resumes execution

## 10. 🔐 Security

### 10.1 Authentication

- JWT-based auth

### 10.2 Authorization

- Tenant-level access control

### 10.3 Data Isolation

- Strict tenant boundaries
- No cross-tenant queries

## 11. 📊 Observability

### 11.1 Logging

- Structured logs (JSON)

### 11.2 Metrics

- Agent execution time
- Queue latency
- Error rates

### 11.3 Tracing

- Correlate events by sessionId
- Distributed tracing (OpenTelemetry)

## 12. ⚠️ Failure Handling

### 12.1 Worker Crash

- Task re-queued

### 12.2 Message Loss

- Kafka guarantees durability

### 12.3 Partial Execution

- Resume via event replay

## 13. 🚀 Deployment Architecture

### 13.1 Suggested Stack

- API: Node.js / NestJS
- Queue: Kafka / Redis Streams
- DB: Postgres
- Cache: Redis
- Infra: Kubernetes

### 13.2 Deployment Units

| Service        | Role         |
| -------------- | ------------ |
| API Gateway    | entry point  |
| Orchestrator   | coordination |
| Worker         | execution    |
| Stream Gateway | WebSocket    |

## 14. 💡 Trade-offs

### SSE vs WebSocket

| SSE     | WebSocket  |
| ------- | ---------- |
| Simple  | Complex    |
| One-way | Two-way    |
| MVP     | Production |

### In-memory vs Distributed

| In-memory   | Distributed    |
| ----------- | -------------- |
| Fast        | Scalable       |
| Not durable | Fault tolerant |

## 15. 🏁 Final Architecture Insight

> The system evolves from:

### MVP

```text
Single runtime + SSE
```

### Production

```text
Distributed event-driven execution platform
```

## 16. 🔥 Final Statement

> This is no longer just an AI app.

It becomes:

> 🚀 A **distributed, event-sourced agent execution platform**

## Consolidated Content: Backend Runtime Context

# ⚙️ THE GLASS BOX — BACKEND SDK & RUNTIME ARCHITECTURE

## 1. 🎯 Overview

The backend of The Glass Box system is a **lightweight Agent Runtime Platform** that simulates the core behavior of modern AI agent frameworks (e.g., Claude Agent SDK, LangGraph).

It is responsible for:

- Executing agents
- Managing agent lifecycle
- Handling parallel execution
- Emitting real-time events
- Supporting human-in-the-loop (HITL)

👉 The backend acts as both:

- **Execution Engine (Runtime)**
- **Developer-facing SDK (Agent abstraction)**

## 2. 🧠 Core Design Principles

### 2.1 Event-Driven Architecture

All agent actions are converted into **events** and streamed to the UI.

> The system is fully observable by design.

### 2.2 Async-first Execution

- All agent operations are asynchronous
- Supports parallel execution via `Promise`

### 2.3 Deterministic State via Events

- No hidden state transitions
- Every meaningful step emits an event

### 2.4 Minimal SDK, Maximum Expressiveness

- Simple API surface
- Powerful enough to simulate real agent workflows

## 3. 🧩 System Components

```text
Agent SDK (Developer API)
        ↓
Runtime Engine (Execution Layer)
        ↓
Event Bus (Emitter)
        ↓
Streaming Layer (SSE)
        ↓
Frontend (Glass Box UI)
```

## 4. 🧬 Agent SDK Design

### 4.1 Agent Definition

```ts
class Agent {
  constructor(private config: {
    name: string;
    run: (ctx: AgentContext, input?: any) => Promise<any>;
  }) {}

  async execute(runtime: Runtime, parentId?: string) {
    const id = runtime.createAgent(this.config.name, parentId);

    const ctx = runtime.createContext(id);

    const result = await this.config.run(ctx);

    runtime.completeAgent(id);

    return result;
  }
}
```

### 4.2 AgentContext (Core API)

```ts
type AgentContext = {
  think: (message: string) => void;
  tool: (name: string, input: any) => Promise<any>;
  spawn: (agent: Agent, input?: any) => Promise<any>;
  askUser: (question: string) => Promise<string>;
};
```

### 4.3 Example Usage

```ts
const ResearchAgent = new Agent({
  name: "ResearchAgent",
  async run(ctx) {
    ctx.think("Searching for information...");

    const data = await ctx.tool("search", { query: "AI trends" });

    const result = await ctx.spawn(SummarizerAgent, data);

    const decision = await ctx.askUser("Proceed with result?");

    return decision;
  }
});
```

## 5. ⚙️ Runtime Engine

### 5.1 Responsibilities

- Manage agent lifecycle
- Generate unique agent IDs
- Create execution context
- Emit events
- Coordinate async execution

### 5.2 Event Model

```ts
type Event =
  | { type: "agent_start"; id: string; parentId?: string }
  | { type: "thinking"; agentId: string; content: string }
  | { type: "tool_call"; agentId: string; tool: string }
  | { type: "spawn"; parent: string; child: string }
  | { type: "ask_user"; agentId: string; question: string }
  | { type: "done"; agentId: string };
```

### 5.3 Runtime Implementation (Simplified)

```ts
class Runtime {
  private listeners: ((event: Event) => void)[] = [];

  onEvent(cb: (event: Event) => void) {
    this.listeners.push(cb);
  }

  emit(event: Event) {
    for (const cb of this.listeners) {
      cb(event);
    }
  }

  createAgent(name: string, parentId?: string) {
    const id = generateId();

    this.emit({ type: "agent_start", id, parentId });

    return id;
  }

  completeAgent(agentId: string) {
    this.emit({ type: "done", agentId });
  }
}
```

## 6. 🔄 Context Implementation

### 6.1 Core Idea

Each agent receives a **bound context** tied to its `agentId`.

### 6.2 Implementation

```ts
createContext(agentId: string): AgentContext {
  return {
    think: (message) => {
      this.emit({ type: "thinking", agentId, content: message });
    },

    tool: async (name, input) => {
      this.emit({ type: "tool_call", agentId, tool: name });

      const result = await fakeTool(name, input);

      return result;
    },

    spawn: async (agent, input) => {
      const childId = generateId();

      this.emit({ type: "spawn", parent: agentId, child: childId });

      return agent.execute(this, agentId);
    },

    askUser: async (question) => {
      this.emit({ type: "ask_user", agentId, question });

      return await waitForUserInput(agentId);
    }
  };
}
```

## 7. ⚡ Parallel Execution Model

### 7.1 Default Behavior

- `spawn()` returns a Promise
- Developers control concurrency

### 7.2 Sequential Execution

```ts
await ctx.spawn(A);
await ctx.spawn(B);
```

### 7.3 Parallel Execution

```ts
await Promise.all([
  ctx.spawn(A),
  ctx.spawn(B)
]);
```

### 7.4 Key Insight

> Parallelism is **explicit and developer-controlled**

## 8. 🧍 Human-in-the-loop (HITL)

### 8.1 Problem

Agents must pause execution and wait for user input.

### 8.2 Solution: Promise Suspension

```ts
const waitingMap = new Map<string, (value: string) => void>();

function waitForUserInput(agentId: string): Promise<string> {
  return new Promise((resolve) => {
    waitingMap.set(agentId, resolve);
  });
}
```

### 8.3 Resume Flow

```ts
function resolveUserInput(agentId: string, answer: string) {
  const resolve = waitingMap.get(agentId);

  if (resolve) {
    resolve(answer);
    waitingMap.delete(agentId);
  }
}
```

### 8.4 Lifecycle

1. Agent calls `askUser`
2. Runtime emits `ask_user`
3. Execution pauses
4. UI collects input
5. Backend resolves Promise
6. Execution resumes

## 9. 🌊 Streaming Layer

### 9.1 Protocol: Server-Sent Events (SSE)

Chosen for simplicity and unidirectional streaming.

### 9.2 Implementation

```ts
app.get("/stream", (req, res) => {
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");

  runtime.onEvent((event) => {
    res.write(`data: ${JSON.stringify(event)}\n\n`);
  });
});
```

### 9.3 Resume Endpoint

```ts
app.post("/resume", (req, res) => {
  const { agentId, answer } = req.body;

  resolveUserInput(agentId, answer);

  res.json({ success: true });
});
```

## 10. 🧪 Tooling Layer (Mocked)

### 10.1 Purpose

- Simulate real-world behavior
- Avoid external dependencies

### 10.2 Example

```ts
async function fakeTool(name: string, input: any) {
  await delay(500);

  return {
    tool: name,
    result: "mock result"
  };
}
```

## 11. 🔁 End-to-End Flow

```text
1. User triggers agent execution
2. Runtime initializes root agent
3. Agent emits events via context
4. Runtime streams events via SSE
5. UI renders trace tree
6. If ask_user → pause
7. User responds → POST /resume
8. Runtime resumes execution
```

## 12. ⚠️ Failure Handling

### Cases

- Lost SSE connection
- Unresolved HITL promise
- Agent crash

### Strategies

- Reconnect SSE
- Timeout for user input
- Wrap agent execution in try/catch

## 13. 🚀 Performance Considerations

- Lightweight event emitter (in-memory)
- No persistent storage (MVP scope)
- Non-blocking async execution

## 14. 🎯 MVP Scope (48h)

### Must-have

- Agent SDK abstraction
- Runtime execution engine
- Event streaming (SSE)
- HITL support

### Nice-to-have

- Agent timeout
- Retry logic
- Event persistence
- WebSocket upgrade

## 15. 💡 Key Insight

> The backend is not just a server.

It is:

> 🔥 A miniature distributed execution engine for AI agents

## 16. 🧩 Summary

This system demonstrates:

- Agent abstraction design
- Event-driven architecture
- Async orchestration
- Real-time streaming systems

## 17. 🏁 Final Note

> This is a **Glass Box AI Runtime**

Where:

- Nothing is hidden
- Everything is observable
- Every action is traceable

