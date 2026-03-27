---
trigger: always_on
---

# Runtime Execution and Reliability

This is the canonical runtime execution document for The Glass Box.
The content below consolidates these previous files:
- model-specification.instructions.md
- advanced-system-spec.instructions.md
- sceduler-design.instructions.md

## Consolidated Content: Execution Model

# ⚙️ THE GLASS BOX — EXECUTION MODEL SPECIFICATION

## 1. 🎯 Purpose

This document defines the **formal execution semantics** of The Glass Box system.

It serves as:

- A **source of truth** for how agents execute
- A **contract between SDK, Runtime, and Workers**
- A **foundation for correctness, scaling, and recovery**

## 2. 🧠 Core Principles

### 2.1 Deterministic via Events

> System state MUST be reconstructable from events.

### 2.2 Async-first Execution

- All operations are asynchronous
- Execution is non-blocking by default

### 2.3 No Hidden State

- All meaningful transitions must emit events
- No implicit side effects allowed

### 2.4 Idempotent Execution

- Tasks must be safe to retry
- Duplicate execution must not corrupt state

## 3. 🧩 Core Execution Entities

### 3.1 Agent

- Logical unit of execution
- Stateless definition
- Executed via runtime

### 3.2 Task

Represents a unit of work scheduled for execution.

```ts
type Task = {
  id: string;
  type: "agent" | "tool" | "hitl";
  agentId: string;
  parentTaskId?: string;
  payload: any;
  status: TaskStatus;
};
```

### 3.3 Event

Represents a fact that occurred.

```ts
type Event = {
  id: string;
  type: string;
  agentId: string;
  taskId?: string;
  payload: any;
  timestamp: number;
};
```

## 4. 🔄 Task State Machine

### 4.1 States

```text
CREATED
  ↓
QUEUED
  ↓
RUNNING
  ↓
WAITING (optional)
  ↓
COMPLETED
  ↓
FAILED (optional)
```

### 4.2 State Definitions

| State     | Meaning               |
| --------- | --------------------- |
| CREATED   | Task initialized      |
| QUEUED    | Waiting for execution |
| RUNNING   | Currently executing   |
| WAITING   | Paused (HITL)         |
| COMPLETED | Finished successfully |
| FAILED    | Execution failed      |

### 4.3 Valid Transitions

```text
CREATED → QUEUED
QUEUED → RUNNING
RUNNING → WAITING
WAITING → RUNNING
RUNNING → COMPLETED
RUNNING → FAILED
FAILED → QUEUED (retry)
```

### 4.4 Invalid Transitions

```text
WAITING → COMPLETED ❌
COMPLETED → RUNNING ❌
FAILED → COMPLETED ❌
```

## 5. ⚙️ Execution Semantics

### 5.1 Agent Execution

```text
Agent.execute()
   ↓
Create Task (type=agent)
   ↓
Scheduler queues task
   ↓
Worker executes task
   ↓
Emit lifecycle events
```

### 5.2 Context Operations Mapping

| SDK Call  | Task       | Events                 |
| --------- | ---------- | ---------------------- |
| think()   | none       | thinking               |
| tool()    | tool task  | tool_call, tool_result |
| spawn()   | agent task | spawn, agent_start     |
| askUser() | hitl task  | ask_user, resume       |

## 6. ⚡ Concurrency Model

### 6.1 Execution Units

- Task = atomic execution unit
- Tasks are independently schedulable

### 6.2 Parallelism

```ts
await Promise.all([
  ctx.spawn(A),
  ctx.spawn(B)
]);
```

### 6.3 Guarantees

- No global ordering guarantee
- Per-task execution is sequential
- Per-agent ordering is best-effort

### 6.4 Isolation

- Each task has isolated context
- No shared mutable state

## 7. 🧍 Blocking & Suspension (HITL)

### 7.1 Suspension Model

```text
RUNNING → WAITING
```

### 7.2 Behavior

- Task execution pauses
- State persisted
- Await external input

### 7.3 Resume Model

```text
WAITING → RUNNING
```

### 7.4 Guarantees

- Resume must be idempotent
- Multiple resume attempts must be safe

## 8. 🔁 Retry & Idempotency

### 8.1 Retry Conditions

- Transient failures
- Worker crash
- Timeout

### 8.2 Retry Strategy

```text
FAILED → QUEUED
```

### 8.3 Idempotency Rules

| Operation       | Requirement             |
| --------------- | ----------------------- |
| Agent execution | must be safe            |
| Tool call       | must handle duplicate   |
| HITL resume     | must not double resolve |

### 8.4 Idempotency Key

```ts
type Task = {
  idempotencyKey?: string;
};
```

## 9. 🔄 Execution Ordering

### 9.1 Within Task

- Strictly ordered

### 9.2 Across Tasks

- No ordering guarantee

### 9.3 Event Ordering

- Eventually consistent
- May arrive out of order

## 10. 🧠 Determinism & Replay

### 10.1 Event Replay

```text
Event Log → Rebuild State → Resume Execution
```

### 10.2 Requirements

- Events must be immutable
- Execution must be reproducible

### 10.3 Non-deterministic Operations

Must be controlled:

- random()
- timestamps
- external APIs

## 11. ⚠️ Failure Model

### 11.1 Failure Types

| Type      | Example         |
| --------- | --------------- |
| Transient | network timeout |
| Permanent | invalid input   |
| System    | crash           |

### 11.2 Handling

- Transient → retry
- Permanent → fail task
- System → recover via replay

## 12. 🧩 Execution Guarantees

### 12.1 At-least-once Execution

- Tasks may run multiple times
- Must be idempotent

### 12.2 Eventual Consistency

- UI state may lag
- System converges over time

### 12.3 No Exactly-once Guarantee

- Simplifies system design
- Delegates safety to idempotency

## 13. 📊 Resource Constraints

### 13.1 Per Task

- CPU-bound or IO-bound

### 13.2 Limits

- max concurrent tasks per worker
- max tasks per session

### 13.3 Backpressure

- queue growth signals overload
- scheduler must throttle

## 14. 🔐 Multi-Tenant Execution

### 14.1 Context Propagation

```ts
type ExecutionContext = {
  tenantId: string;
  sessionId: string;
};
```

### 14.2 Isolation

- No cross-tenant execution
- Tasks partitioned by tenant

## 15. 💡 Key Insights

### Insight #1

> Execution = Task State Machine + Event Stream

### Insight #2

> Tasks are ephemeral. Events are permanent.

### Insight #3

> Determinism is achieved through event replay

## 16. 🏁 Summary

The execution model defines:

- How tasks are created, scheduled, and executed
- How agents interact with runtime
- How system handles concurrency and failure
- How state is reconstructed

## 17. 🔥 Final Statement

> This system behaves as a **distributed, event-driven state machine executing task graphs with asynchronous suspension and recovery**

## Consolidated Content: Advanced System Specs

<!-- Tip: Use /create-instructions in chat to generate content with agent assistance -->

# 🧩 THE GLASS BOX — ADVANCED SYSTEM SPECS

# 1. 🔄 STATE MACHINE SPECIFICATION

## 1.1 Purpose

Define **valid state transitions** and enforce correctness of execution.

## 1.2 Task State Machine

### States

```text
CREATED → QUEUED → RUNNING → WAITING → COMPLETED
                           ↘ FAILED
```

## 1.3 Formal Definition

```ts
type TaskState =
  | "CREATED"
  | "QUEUED"
  | "RUNNING"
  | "WAITING"
  | "COMPLETED"
  | "FAILED";
```

## 1.4 Transition Table

| From    | To             | Valid |
| ------- | -------------- | ----- |
| CREATED | QUEUED         | ✅     |
| QUEUED  | RUNNING        | ✅     |
| RUNNING | WAITING        | ✅     |
| WAITING | RUNNING        | ✅     |
| RUNNING | COMPLETED      | ✅     |
| RUNNING | FAILED         | ✅     |
| FAILED  | QUEUED (retry) | ✅     |

## 1.5 Invalid Transitions

| From      | To        | Reason            |
| --------- | --------- | ----------------- |
| WAITING   | COMPLETED | must resume first |
| COMPLETED | RUNNING   | terminal state    |
| FAILED    | COMPLETED | must retry        |

## 1.6 Transition Guard

```ts
function canTransition(from: TaskState, to: TaskState): boolean {
  // strict validation
}
```

## 1.7 Event-driven Transition

| Event        | Transition          |
| ------------ | ------------------- |
| task_queued  | CREATED → QUEUED    |
| task_started | QUEUED → RUNNING    |
| ask_user     | RUNNING → WAITING   |
| resume       | WAITING → RUNNING   |
| task_done    | RUNNING → COMPLETED |
| task_failed  | RUNNING → FAILED    |

## 1.8 Agent-level State (Derived)

```text
Agent = aggregate(Task states)
```

# 2. 💥 FAILURE MODEL

## 2.1 Failure Categories

### 1. Transient

- network timeout
- rate limit

👉 Action: retry

### 2. Permanent

- invalid input
- schema error

👉 Action: fail fast

### 3. System

- worker crash
- infra outage

👉 Action: replay + recover

## 2.2 Retry Policy

```ts
type RetryPolicy = {
  maxAttempts: number;
  backoff: "exponential";
  baseDelayMs: number;
};
```

### Example

```text
1s → 2s → 4s → 8s
```

## 2.3 Idempotency Requirement

- Every task MUST be retry-safe
- Tool calls must support deduplication

## 2.4 Failure Event Schema

```ts
type FailureEvent = {
  type: "task_failed";
  errorType: "transient" | "permanent" | "system";
  message: string;
};
```

## 2.5 Dead Letter Queue (DLQ)

- Tasks exceeding retry limit → DLQ
- Manual inspection required

## 2.6 Timeout Handling

```ts
timeoutMs per task
```

→ auto-fail + retry

# 3. 📊 OBSERVABILITY SPEC

## 3.1 Goals

- Debug execution
- Monitor performance
- Trace full lifecycle

## 3.2 Trace Model

```text
traceId
 └── sessionId
      └── agentId
           └── taskId
```

## 3.3 Logging (Structured)

```json
{
  "level": "info",
  "timestamp": "...",
  "traceId": "...",
  "event": "task_started",
  "taskId": "...",
  "agentId": "..."
}
```

## 3.4 Metrics

### Core Metrics

| Metric         | Meaning                |
| -------------- | ---------------------- |
| task_latency   | execution time         |
| queue_lag      | delay before execution |
| retry_count    | failure indicator      |
| hitl_wait_time | UX metric              |

### Aggregations

- p50, p95, p99

## 3.5 Distributed Tracing

- OpenTelemetry compatible
- Span per task

## 3.6 Alerting

| Condition        | Alert |
| ---------------- | ----- |
| queue lag high   | ⚠️    |
| error rate spike | 🚨    |
| HITL delay > SLA | 🚨    |

# 4. 🚀 LOAD & CAPACITY PLANNING

## 4.1 Target Metrics (MVP → Production)

```text
Concurrent sessions: 1k+
Tasks/sec: 5k–10k
Event throughput: 10k+/sec
Latency (stream): <200ms
```

## 4.2 Capacity Model

### Per Worker

```text
10–50 concurrent tasks
CPU-bound vs IO-bound
```

### Horizontal Scaling

```text
workers_needed = total_tasks / tasks_per_worker
```

## 4.3 Bottlenecks

| Layer | Risk                |
| ----- | ------------------- |
| Queue | throughput          |
| DB    | write amplification |
| UI    | render performance  |

## 4.4 Scaling Strategy

- Auto-scale workers via queue lag
- Partition by sessionId

## 4.5 Load Shedding

- Drop low priority tasks
- Reject new sessions

# 5. 🔄 DATA CONSISTENCY MODEL

## 5.1 Consistency Type

> Eventual Consistency

## 5.2 Guarantees

- System converges over time
- UI may lag behind

## 5.3 Event Ordering

- Per partition: ordered
- Global: unordered

## 5.4 Duplicate Handling

```ts
eventId used for deduplication
```

## 5.5 Idempotent Projection

```ts
applyEvent(event) {
  if (seen(event.id)) return;
}
```

## 5.6 Read Model

```text
Event Log → Projection → UI State
```

## 5.7 Trade-offs

| Strong Consistency | Eventual |
| ------------------ | -------- |
| slow               | fast     |
| complex            | scalable |

## 5.8 Conflict Resolution

- last-write-wins (simple)
- or version-based merge

# 🏁 FINAL SUMMARY

This document defines:

- ✅ State correctness (State Machine)
- ✅ Failure resilience (Failure Model)
- ✅ Observability (Tracing, metrics)
- ✅ Scalability (Capacity planning)
- ✅ Data consistency (Eventual model)

# 🔥 FINAL STATEMENT

> The system is not just scalable — it is **predictable, observable, and recoverable under failure**

## Consolidated Content: Scheduler Design

# 🧠 THE GLASS BOX — SCHEDULER DESIGN SPECIFICATION

## 1. 🎯 Purpose

This document defines the **task scheduling strategy** for The Glass Box system.

It ensures:

- Fair resource allocation across tenants
- Efficient execution of tasks
- System stability under load
- Scalable distributed execution

## 2. 🧠 Core Principles

### 2.1 Fairness First

> No single tenant or session can monopolize resources.

### 2.2 Backpressure Awareness

- System must detect overload
- Must degrade gracefully

### 2.3 Priority-aware Execution

- Critical tasks should run earlier
- Support future extensibility

### 2.4 Distributed-Friendly

- Scheduler must work across multiple workers
- Stateless coordination where possible

## 3. 🧩 Scheduler Architecture

```text id="z4a1tq"
Task Producer (Runtime)
        ↓
   Task Queue (Kafka / Redis)
        ↓
   Scheduler (logical layer)
        ↓
   Worker Pool
        ↓
   Task Execution
```

## 4. 🔑 Core Concepts

### 4.1 Task Queue

- Central buffer for all tasks
- Partitioned by `sessionId` or `tenantId`

### 4.2 Scheduler

Logical layer responsible for:

- Selecting next task
- Enforcing policies
- Applying throttling

### 4.3 Worker

- Pull-based execution unit
- Executes tasks independently

## 5. ⚙️ Scheduling Policies

### 5.1 Default Policy: Weighted Fair Scheduling

#### Goal

Balance load across tenants while allowing prioritization.

#### Model

```text id="o3k0s6"
Tenant A → weight 2
Tenant B → weight 1
```

👉 A gets 2x scheduling share of B

### 5.2 Within Tenant: FIFO

```text id="3pf2j5"
Tasks in same session → FIFO
```

### 5.3 Cross-Tenant: Round Robin

```text id="l4r0cd"
A → B → A → A → B → ...
```

## 6. ⚡ Priority Levels

### 6.1 Task Priority

```ts id="i2k4k6"
type Priority = "low" | "normal" | "high" | "critical";
```

### 6.2 Use Cases

| Priority | Example              |
| -------- | -------------------- |
| critical | HITL resume          |
| high     | user-triggered agent |
| normal   | background agent     |
| low      | batch jobs           |

### 6.3 Priority Queue Strategy

- Separate queues per priority
- Always drain higher priority first

## 7. 🔄 Scheduling Flow

```text id="7p0p6c"
1. Task created
2. Task pushed to queue
3. Worker requests task
4. Scheduler selects task
5. Task assigned to worker
6. Task executed
```

## 8. 🧍 HITL Scheduling

### 8.1 Resume Priority

- HITL resume tasks MUST be `critical`

### 8.2 Latency Requirement

```text id="7b5eqx"
Resume latency < 100ms target
```

### 8.3 Queue Strategy

- Dedicated HITL queue (optional)

## 9. 🔁 Retry Strategy

### 9.1 Retry Queue

- Failed tasks re-enqueued

### 9.2 Backoff Policy

```text id="c8f81b"
retry_delay = base * 2^attempt
```

### 9.3 Retry Limits

- maxAttempts = configurable

## 10. ⚠️ Backpressure Handling

### 10.1 Detection

- Queue length threshold
- Worker utilization > 80%

### 10.2 Actions

| Condition     | Action                  |
| ------------- | ----------------------- |
| mild overload | slow scheduling         |
| high overload | reject new tasks        |
| critical      | drop low-priority tasks |

### 10.3 Rate Limiting

```ts id="r3vxkq"
maxTasksPerTenant = N
maxTasksPerSession = M
```

## 11. ⚡ Concurrency Control

### 11.1 Worker-level Limits

```ts id="zq1ntg"
maxConcurrentTasks = 10
```

### 11.2 Session-level Limits

- Prevent explosion from one session

### 11.3 Global Limits

- Protect system stability

## 12. 🧠 Task Selection Algorithm (Simplified)

```ts id="zw7mj0"
function pickNextTask() {
  for (tenant of tenantsRoundRobin) {
    if (tenant.hasHighPriorityTask()) {
      return tenant.dequeueHighPriority();
    }

    return tenant.dequeueFIFO();
  }
}
```

## 13. 🔐 Multi-Tenant Isolation

### 13.1 Fairness Guarantee

- Each tenant gets proportional share

### 13.2 Isolation Rules

- No starvation
- No cross-tenant blocking

## 14. 📊 Metrics & Monitoring

### 14.1 Key Metrics

- queue length
- task latency (p50, p95)
- scheduling delay
- worker utilization

### 14.2 Alerts

- queue backlog too high
- retry rate spike
- HITL latency breach

## 15. 🚀 Scaling Strategy

### 15.1 Horizontal Scaling

- Add more workers
- Partition queue

### 15.2 Partition Strategy

```text id="m7h8rc"
partition key = sessionId
```

### 15.3 Elastic Scaling

- Auto-scale workers based on queue lag

## 16. ⚠️ Failure Scenarios

### 16.1 Worker Crash

- Task returned to queue

### 16.2 Duplicate Execution

- Must be handled via idempotency

### 16.3 Queue Failure

- Persisted queue required (Kafka)

## 17. 💡 Design Trade-offs

### FIFO vs Priority

| FIFO   | Priority   |
| ------ | ---------- |
| fair   | responsive |
| simple | complex    |

### Push vs Pull Workers

| Push          | Pull          |
| ------------- | ------------- |
| complex       | simple        |
| less scalable | more scalable |

👉 Choose: **Pull model**

## 18. 🏁 Summary

The scheduler:

- Balances fairness and performance
- Controls system load
- Enables distributed execution
- Ensures responsive HITL flows

## 19. 🔥 Final Statement

> The scheduler is the **control plane** of the execution system — it decides *what runs, when, and how fast*

