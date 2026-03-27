---
trigger: always_on
---

# 🧬 THE GLASS BOX — AGENT SDK ARCHITECTURE SPECIFICATION

## 1. 🎯 Purpose

This document defines the **architecture, contracts, and behaviors** of the Agent SDK used in The Glass Box system.

It serves as:

- A **blueprint for implementation**
- A **contract between SDK and Runtime**
- A **guideline for extending agent capabilities**

## 2. 🧠 Design Goals

### 2.1 Simplicity First

- Minimal API surface
- Easy to understand for junior developers

### 2.2 Deterministic Execution via Events

- Every action must produce an event
- No hidden side effects

### 2.3 Composability

- Agents can spawn other agents
- Supports recursive workflows

### 2.4 Async-Native

- All operations are Promise-based
- Built for concurrency

### 2.5 Observability by Design

- SDK must integrate tightly with runtime event system

## 3. 🧩 High-Level Architecture

```text id="1rpnss"
        Developer Code
              ↓
          Agent SDK
              ↓
     Execution Context Layer
              ↓
         Runtime Adapter
              ↓
        Event Emission Layer
```

## 4. 🔑 Core Abstractions

### 4.1 Agent

#### Definition

```ts id="0y05pg"
class Agent<TInput = any, TOutput = any> {
  name: string;

  constructor(config: {
    name: string;
    run: (ctx: AgentContext, input: TInput) => Promise<TOutput>;
  });

  execute(runtime: Runtime, parentId?: string, input?: TInput): Promise<TOutput>;
}
```

#### Responsibilities

- Encapsulate business logic
- Define execution boundary
- Remain stateless (no internal mutable state)

#### Constraints

- Must not directly emit events
- Must only interact via `AgentContext`

## 4.2 AgentContext

### Definition

```ts id="p2qfxb"
type AgentContext = {
  think(message: string): void;

  tool<TInput, TOutput>(
    name: string,
    input: TInput
  ): Promise<TOutput>;

  spawn<TInput, TOutput>(
    agent: Agent<TInput, TOutput>,
    input: TInput
  ): Promise<TOutput>;

  askUser(question: string): Promise<string>;
};
```

### Responsibilities

- Provide controlled interaction with runtime
- Ensure all operations are observable
- Abstract runtime complexity

### Behavioral Guarantees

- All methods must:

  - Emit corresponding events
  - Be safe for concurrent execution
  - Be idempotent where applicable

## 4.3 Runtime Adapter (SDK ↔ Runtime Bridge)

### Purpose

Decouple SDK logic from runtime implementation.

### Interface

```ts id="t7bxkk"
interface RuntimeAdapter {
  createAgent(name: string, parentId?: string): string;

  emit(event: Event): void;

  complete(agentId: string): void;

  waitForUser(agentId: string): Promise<string>;

  executeAgent(
    agent: Agent<any, any>,
    parentId: string,
    input?: any
  ): Promise<any>;
}
```

### Key Insight

> SDK should never depend on concrete runtime implementation.

## 5. 🔄 Execution Lifecycle

### 5.1 Agent Execution Flow

```text id="6v5xfi"
1. Agent.execute()
2. RuntimeAdapter.createAgent()
3. Context created
4. Agent.run(ctx)
5. Context methods emit events
6. Agent completes
7. RuntimeAdapter.complete()
```

### 5.2 Lifecycle Events

| Phase      | Event       |
| ---------- | ----------- |
| Start      | agent_start |
| Thinking   | thinking    |
| Tool usage | tool_call   |
| Spawn      | spawn       |
| User input | ask_user    |
| End        | done        |

## 6. ⚙️ Context Method Specifications

### 6.1 think()

#### Purpose

Emit reasoning step

```ts id="ng3yql"
ctx.think("Analyzing data...");
```

#### Behavior

- Fire-and-forget
- Emits `thinking` event

### 6.2 tool()

#### Purpose

Execute external capability

```ts id="c1r0e6"
await ctx.tool("search", { query: "AI" });
```

#### Behavior

1. Emit `tool_call`
2. Call tool handler
3. Return result

#### Constraints

- Must not block event emission
- Must handle errors gracefully

### 6.3 spawn()

#### Purpose

Create sub-agent

```ts id="mfh0y1"
await ctx.spawn(SubAgent, input);
```

#### Behavior

1. Generate child agent ID
2. Emit `spawn`
3. Execute child agent
4. Return result

#### Concurrency Model

- Non-blocking until awaited
- Supports parallel execution

### 6.4 askUser()

#### Purpose

Pause execution for user input

```ts id="78r3k7"
const answer = await ctx.askUser("Continue?");
```

#### Behavior

1. Emit `ask_user`
2. Suspend execution (Promise)
3. Resume when resolved

#### Constraints

- Must not resolve automatically
- Must persist pending state externally

## 7. ⚡ Concurrency Model

### 7.1 Execution Types

| Type       | Behavior        |
| ---------- | --------------- |
| Sequential | await each call |
| Parallel   | Promise.all     |

### 7.2 Example

```ts id="z8b0o0"
await Promise.all([
  ctx.spawn(A),
  ctx.spawn(B)
]);
```

### 7.3 Guarantees

- No shared mutable state
- Each agent has isolated context
- Event order is not guaranteed globally

## 8. 🧍 Human-in-the-loop (HITL)

### 8.1 State Model

```ts id="wpl3w4"
type WaitingState = {
  agentId: string;
  resolve: (value: string) => void;
};
```

### 8.2 Requirements

- Must support multiple concurrent waits
- Must handle late responses
- Must avoid memory leaks

### 8.3 Edge Cases

- Duplicate resume
- Missing agentId
- Timeout (optional)

## 9. 🔐 Error Handling

### 9.1 Agent Errors

- Wrap `run()` in try/catch
- Emit optional `error` event

### 9.2 Tool Errors

- Return fallback result
- Do not crash runtime

### 9.3 SDK Guarantees

- No uncaught exceptions propagate to runtime
- All failures are observable

## 10. 🧪 Testing Strategy

### 10.1 Unit Tests

- Agent execution
- Context methods
- Event emission

### 10.2 Integration Tests

- Multi-agent workflows
- HITL scenarios
- Parallel execution

### 10.3 Mocking

- RuntimeAdapter
- Tool handlers

## 11. 🚀 Extensibility

### 11.1 Future Features

- Memory system
- Tool registry
- Retry policies
- Agent middleware

### 11.2 Plugin Pattern

```ts id="8h7a9v"
agent.use(plugin);
```

## 12. 📦 Suggested Folder Structure

```text id="3l0g5u"
sdk/
 ├── agent.ts
 ├── context.ts
 ├── runtime-adapter.ts
 ├── types.ts
 ├── events.ts
 └── utils/
```

## 13. 💡 Key Insights

### Insight #1

> SDK is NOT the runtime

It is an abstraction layer.

### Insight #2

> Context is the ONLY interface

Agents must never bypass it.

### Insight #3

> Everything is an event

This enables observability and replay.

## 14. 🏁 Summary

The Agent SDK provides:

- A clean abstraction for agent logic
- A strict contract with runtime
- Full observability via event emission
- Support for async + parallel workflows

## 15. 🎯 Final Statement

> This SDK is a **minimal but complete foundation** for building observable AI agent systems.

