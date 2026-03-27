---
trigger: always_on
---

# 🧊 THE GLASS BOX — UI ARCHITECTURE & FLOW DESIGN

## 1. 🎯 Overview

The Glass Box UI is a **real-time observability interface** for AI agent systems.

Unlike traditional chat applications (black-box), this UI exposes:

- Agent reasoning (thinking)
- Tool interactions
- Sub-agent orchestration (parallel execution)
- Human-in-the-loop (HITL) interruptions

👉 The goal is to transform a **flat event stream** into a **structured, interactive trace tree**.

## 2. 🧠 Core Concept

### Black Box vs Glass Box

| Black Box         | Glass Box                      |
| ----------------- | ------------------------------ |
| Only final answer | Full reasoning trace           |
| No visibility     | Full transparency              |
| Linear chat       | Tree-based execution           |
| Stateless UI      | Stateful runtime visualization |

## 3. 📡 Input: Event Stream

The UI consumes a **real-time stream of events** from backend (via SSE/WebSocket).

### Event Format (Simplified)

```json
{
  "type": "thinking",
  "agentId": "A1",
  "content": "Analyzing user query..."
}
```

### Supported Event Types

```ts
type Event =
  | { type: "agent_start"; id: string; parentId?: string }
  | { type: "thinking"; agentId: string; content: string }
  | { type: "tool_call"; agentId: string; tool: string }
  | { type: "spawn"; parent: string; child: string }
  | { type: "ask_user"; agentId: string; question: string }
  | { type: "done"; agentId: string };
```

## 4. 🔄 Data Transformation: Flat → Tree

### Problem

Incoming data is **flat and unordered**:

```text
Event Stream:
A2 thinking
A1 start
spawn A1 → A2
```

### Solution

The UI builds a **dynamic in-memory tree**:

```text
A1
 ├── thinking
 └── A2
      └── thinking
```

## 5. 🧬 UI State Model

### Agent Node

```ts
type AgentNode = {
  id: string;
  parentId: string | null;
  children: string[];

  status: "running" | "waiting_user" | "done";

  events: Event[];

  createdAt: number;
};
```

### Global Store

```ts
type Store = {
  nodes: Record<string, AgentNode>;
  addEvent: (event: Event) => void;
};
```

## 6. ⚙️ Event Processing Pipeline

### Core Logic

```ts
function handleEvent(event: Event) {
  switch (event.type) {
    case "agent_start":
      createNode(event.id);
      break;

    case "spawn":
      linkParentChild(event.parent, event.child);
      break;

    case "thinking":
    case "tool_call":
      appendEvent(event.agentId, event);
      break;

    case "ask_user":
      updateStatus(event.agentId, "waiting_user");
      break;

    case "done":
      updateStatus(event.agentId, "done");
      break;
  }
}
```

### Key Principles

- ✅ Idempotent updates (safe for duplicate events)
- ✅ Order-independent processing
- ✅ Lazy node creation (handle missing parents)

## 7. 🌳 UI Structure

### Component Hierarchy

```tsx
<TraceTree rootId="A1" />
```

```tsx
function TraceTree({ nodeId }) {
  return (
    <div>
      <NodeHeader />
      <EventList />
      <Children />
    </div>
  );
}
```

### Visual States

| Status       | UI Behavior       |
| ------------ | ----------------- |
| running      | spinner animation |
| waiting_user | input box         |
| done         | check icon        |

## 8. ⚡ Parallel Execution Visualization

### Problem

Multiple sub-agents execute simultaneously.

### UI Requirement

- Render **branching structure**
- Maintain **independent node states**
- Avoid re-render conflicts

### Strategy

- Each node updates independently
- Use normalized store (map instead of nested object)
- Avoid full tree re-render

## 9. 🧍 Human-in-the-loop (HITL)

### Flow

1. Backend emits:

```json
{ "type": "ask_user", "agentId": "A1", "question": "Continue?" }
```

2. UI:

- Mark node as `waiting_user`
- Render input box inline

3. User submits response:

```http
POST /resume
{
  "agentId": "A1",
  "answer": "yes"
}
```

4. Backend resumes execution
5. UI continues streaming

### UX Requirements

- Inline interaction (no modal)
- Preserve context
- No UI reset

## 10. 🌊 Streaming Layer

### SSE Connection

```ts
const evtSource = new EventSource("/api/stream");

evtSource.onmessage = (e) => {
  const event = JSON.parse(e.data);
  handleEvent(event);
};
```

### Reconnection Strategy

- Auto reconnect on failure
- Resume state without reset
- Ignore duplicate events

## 11. 🧪 Error Handling

### Cases to handle

- Missing parent node
- Out-of-order events
- Duplicate events
- Network disconnect

### Strategy

- Defensive node creation
- Idempotent updates
- Retry stream connection

## 12. 🚀 Performance Considerations

### Risks

- High-frequency event stream
- Deep tree rendering

### Optimizations

- Normalize state (O(1) lookup)
- Memoized components
- Incremental rendering
- Optional batching updates

## 13. 🎯 MVP Scope (48h)

### Must-have

- SSE streaming
- Tree visualization
- Event rendering
- HITL interaction

### Nice-to-have

- Collapse/expand nodes
- Timeline view
- Search/filter
- Debug panel

## 14. 🧩 Summary

The Glass Box UI is:

> 🔥 A real-time distributed system visualizer for AI agents

It combines:

- Stream processing
- State management
- Tree transformation
- Interactive UI (HITL)

## 15. 💡 Key Insight

> This is NOT a chat UI.

It is:

> ✅ A live execution debugger for AI systems

