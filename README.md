# Glass Box Chat

Most AI chat apps show only the final answer.
You do not see how the AI thinks.
You do not see what tools it calls.
You do not see why it made a decision.

**Glass Box Chat** solves that problem.

It is an AI chat application with a live transparency layer.
It streams the agent workflow to the screen in real time.
You can watch thoughts, tool calls, sub-agent activity, and completion states as they happen.

This project is built as a debugging interface for AI agents.
It helps users understand, test, and trust the system.

---

## Design Documents

Technical design documents are available in two forms:

### In this repository

- [Pipeline Architecture](docs/pipeline-architecture.md)
- [Agent Execution Flow](docs/agent-execution.md)

### On GitHub Wiki

- [Pipeline Architecture](https://github.com/phattpde140043/Glass_box_chat/wiki/Pipeline-Architecture)
- [Agent Execution Architecture](https://github.com/phattpde140043/Glass_box_chat/wiki/Agent-execution--Architecture)

These documents explain the system from two angles:

- end-to-end runtime pipeline and streaming architecture
- internal agent execution lifecycle and orchestration model

---

## Problem

Traditional AI chatbots are black boxes.

- You send a message.
- You wait.
- You get an answer.

That is not enough for real debugging.
That is not enough for trust.
That is not enough for learning.

This project adds a clear visibility layer on top of the AI runtime.

---

## Demo

Public deployment is not attached to this repository yet.

You can run the full project locally:

- Backend: `./run-backend.sh` or `run-backend.cmd`
- Frontend: `./run-frontend.sh` or `run-frontend.cmd`

Recommended demo views:

- Chat interface
- Execution trace panel
- Tool call visualization
- Multi-step reasoning flow

---

## What It Looks Like

The interface is designed to make agent execution observable in real time.

- **Chat Panel**: standard conversational interface for user input and AI output
- **Execution Trace Panel**: structured live view of the runtime
- **Trace View Includes**: reasoning steps, tool calls, sub-agent hierarchy, timing, and completion status

The system does not show only raw logs.
It reconstructs a **trace tree** from the event stream.
This helps users understand how the final answer was produced.

---

## Architecture

```text
User (browser)
    ↓
Next.js Frontend
    ↓  REST + SSE
FastAPI Backend
    ↓
Agent Runtime Engine
    ├── LLM Providers (Claude / Gemini)
    ├── Tool Executor
    └── Sub-agent Orchestrator
    ↓
Event Stream
    ↓
Trace UI
```

The backend streams runtime events over **SSE**.
The frontend receives a flat event stream.
It groups events by session and message.
It then builds a readable trace view for the user.

---

## Core Features

### Chat

- Streaming responses
- Multi-turn conversation
- Session-aware message flow

### Transparency Layer

Each important agent action emits a typed event.

```json
{ "event": "thinking", "detail": "Parsing the user query...", "agent": "planner" }
{ "event": "tool_call", "detail": "Calling weather tool", "agent": "planner" }
{ "event": "subagent_start", "detail": "Spawning research agent", "agent": "planner" }
{ "event": "node_done", "detail": "Finished planning node", "agent": "planner" }
```

The UI renders these events as a live trace tree.
This is more useful than a simple log list.

### Agent Runtime

- Single-agent and multi-agent execution
- DAG-style task flow
- Sub-agent spawning
- Human-in-the-loop pause and resume
- Replayable event history

---

## Event Model

All important runtime events are:

- Ordered
- Serializable
- Replayable
- Linked to a session and message
- Stored with `createdAt` timestamps

This allows the system to reconstruct one full run after it finishes.
It also allows the UI to explain the run while it is still in progress.

---

## AI Design

| Choice | Reason |
|---|---|
| Claude + Gemini | Flexible provider support |
| Custom runtime | Full control over event emission and execution flow |
| SSE | Simple and effective for one-way live updates |
| Event-driven execution | Every state change is visible and auditable |

Known limitations:

- Multi-agent runs can increase latency
- LLM output can still hallucinate
- The trace explains the process, but it does not guarantee factual correctness
- Persistent memory between sessions is not implemented yet

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 15, React, Tailwind CSS |
| Backend | FastAPI, Python 3.11+ |
| AI Providers | Anthropic Claude, Google Gemini |
| Streaming | SSE |
| Monorepo | Turborepo, pnpm |
| Shared Packages | `@glassbox/sdk`, `@glassbox/types`, `@glassbox/runtime` |

---

## How This Project Meets Role Requirements

### Problem Solving

The project turns a hard AI problem into a visible system.
It makes agent execution observable and easier to debug.

### Builder DNA and AI Fluency

- Built a full-stack AI product
- Implemented custom agent runtime behavior
- Added tool calling and multi-agent orchestration
- Streamed live execution data to the UI

### Learning Velocity

The project combines several areas at once:

- AI provider integration
- Streaming systems
- Event-driven runtime design
- Trace visualization

### Agency and Communication

- Designed the architecture independently
- Documented trade-offs clearly
- Used shared contracts across frontend and backend

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 20+
- pnpm 9+

### Backend

```bash
# macOS / Linux
./run-backend.sh

# Windows
run-backend.cmd
```

The script creates a virtual environment.
It installs dependencies from the lock file when available.
It then starts the FastAPI server.

### Frontend

```bash
# macOS / Linux
./run-frontend.sh

# Windows
run-frontend.cmd
```

### Environment

Create `apps/api/.env`:

```env
ANTHROPIC_API_KEY=your_key_here
GOOGLE_API_KEY=your_key_here
```

---

## Project Structure

```text
apps/
  api/          # FastAPI backend and runtime stream
  web/          # Next.js frontend and trace UI
packages/
  sdk/          # Agent SDK abstractions
  types/        # Shared types and Zod schemas
  runtime/      # Runtime adapter package
docs/
  migration/    # Migration notes and checkpoints
```

---

## Design Doc Status

This README is the current one-page design summary for the project.
A separate design document can be added later under `docs/` if needed.

---

## Design Decisions

### Why not LangChain?

This project needs precise control over runtime events.
That control is the core product value.

### Why SSE instead of WebSocket?

The main data flow is server to client.
SSE is simpler to deploy, inspect, and debug.

### Why a monorepo?

The SDK, frontend, and shared contracts evolve together.
The monorepo keeps them aligned.

---

## Tests

```bash
# Backend
pytest

# Frontend
pnpm --filter web test
```

---

## Future Improvements

- Public demo deployment
- Screenshot or GIF walkthrough
- Persistent trace storage
- RAG support
- Visual DAG graph for multi-agent runs
- Shareable trace links
- Separate one-page design document under `docs/`

---

## Author

Built as a capstone project about transparent AI agent systems.

