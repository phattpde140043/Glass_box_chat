---
trigger: always_on
---

# 📦 THE GLASS BOX — REPO STRUCTURE & CODING CONVENTION (PRODUCTION)

## 1. 🎯 Overview

This document defines:

- Monorepo structure
- Module boundaries
- Coding conventions
- Naming standards
- Best practices for scalability & maintainability

## 2. 🧱 Monorepo Strategy

### 2.1 Why Monorepo?

- Shared types between frontend & backend
- Centralized SDK
- Easier refactoring
- Strong type safety across system

### 2.2 Tooling

Recommended:

- **pnpm workspaces**
- **Turborepo** (optional for caching/build)

## 3. 📁 Root Structure

```text
glass-box/
├── apps/
│   ├── web/                # Frontend (Next.js)
│   └── api/                # Backend (Node.js / NestJS)
│
├── packages/
│   ├── sdk/                # Agent SDK
│   ├── runtime/            # Runtime engine
│   ├── types/              # Shared types
│   ├── ui/                 # Shared UI components (optional)
│   └── config/             # ESLint, TS config
│
├── infra/                  # Deployment (Docker, k8s)
├── scripts/                # Dev scripts
├── docs/                   # Design docs
│
├── package.json
├── pnpm-workspace.yaml
└── turbo.json
```

## 4. 🧩 Package-Level Structure

### 4.1 SDK Package

```text
packages/sdk/
├── src/
│   ├── agent/
│   │   ├── agent.ts
│   │   └── agent.types.ts
│   │
│   ├── context/
│   │   ├── context.ts
│   │   └── context.types.ts
│   │
│   ├── runtime-adapter/
│   │   └── runtime-adapter.ts
│   │
│   ├── events/
│   │   ├── events.ts
│   │   └── event.types.ts
│   │
│   └── index.ts
```

### 4.2 Runtime Package

```text
packages/runtime/
├── src/
│   ├── core/
│   │   ├── runtime.ts
│   │   ├── scheduler.ts
│   │   └── agent-manager.ts
│   │
│   ├── hitl/
│   │   ├── hitl-manager.ts
│   │
│   ├── event-bus/
│   │   ├── event-bus.ts
│   │
│   ├── adapters/
│   │   ├── memory-adapter.ts
│   │   ├── redis-adapter.ts
│   │
│   └── index.ts
```

### 4.3 API App

```text
apps/api/
├── src/
│   ├── modules/
│   │   ├── agent/
│   │   │   ├── agent.controller.ts
│   │   │   ├── agent.service.ts
│   │   │
│   │   ├── stream/
│   │   │   ├── stream.controller.ts
│   │   │
│   │   ├── hitl/
│   │   │   ├── hitl.controller.ts
│   │
│   ├── common/
│   │   ├── middleware/
│   │   ├── filters/
│   │   ├── interceptors/
│   │
│   └── main.ts
```

### 4.4 Frontend App

```text
apps/web/
├── src/
│   ├── components/
│   │   ├── trace-tree/
│   │   ├── event-list/
│   │   ├── node-card/
│   │
│   ├── store/
│   │   ├── agent-store.ts
│   │
│   ├── hooks/
│   │   ├── use-stream.ts
│   │
│   ├── services/
│   │   ├── api.ts
│   │
│   ├── pages/
│   └── app/
```

## 5. 🧠 Layered Architecture Rules

### 5.1 Dependency Direction

```text
apps → packages
runtime → sdk
sdk → types
```

### ❌ Forbidden

- sdk → runtime
- frontend → runtime internals
- circular dependencies

## 6. 🏷️ Naming Conventions

### 6.1 Files

| Type      | Convention |
| --------- | ---------- |
| files     | kebab-case |
| classes   | PascalCase |
| variables | camelCase  |

### Example

```ts
agent-manager.ts
class AgentManager {}
```

### 6.2 Event Names

```ts
"agent_start"
"tool_call"
"ask_user"
```

👉 snake_case for consistency across systems

## 7. 🔒 Type Safety Rules

### 7.1 No `any`

❌

```ts
function fn(data: any) {}
```

✅

```ts
function fn(data: Event) {}
```

### 7.2 Shared Types

All shared types must live in:

```text
packages/types/
```

### 7.3 Event Schema (strict)

```ts
type Event =
  | { type: "agent_start"; ... }
  | { type: "thinking"; ... };
```

## 8. ⚙️ Coding Conventions

### 8.1 Functional Core, Imperative Shell

- Business logic → pure functions
- Side effects → isolated

### 8.2 Immutability

❌ mutate state

✅ return new state

### 8.3 Error Handling

```ts
try {
  await run();
} catch (e) {
  emitError(e);
}
```

### 8.4 Async Rules

- Always use async/await
- No unhandled promises

## 9. 🧪 Testing Strategy

### 9.1 Structure

```text
__tests__/
*.spec.ts
```

### 9.2 Levels

- Unit (SDK, runtime)
- Integration (agent flows)
- E2E (UI + backend)

## 10. 🧹 Linting & Formatting

### Tools

- ESLint
- Prettier

### Rules

- No unused vars
- Explicit return types
- Consistent imports

## 11. 📦 Git Workflow

### Branch Naming

```text
feature/agent-sdk
fix/hitl-bug
chore/refactor-runtime
```

### Commit Convention

```text
feat: add agent spawn logic
fix: resolve race condition in store
chore: cleanup unused files
```

## 12. 🔁 CI/CD

### Pipeline

1. Lint
2. Type check
3. Test
4. Build

### Optional

- Preview deploy (Vercel)

## 13. 🚀 Performance Guidelines

- Avoid deep object nesting
- Use normalized state
- Memoize UI components
- Batch updates when needed

## 14. 🔐 Security Practices

- Validate all inputs
- Sanitize user responses
- Avoid exposing internal IDs

## 15. 💡 Key Engineering Insights

### Insight #1

> Structure > Code

### Insight #2

> Type safety = scalability

### Insight #3

> Separation of concerns is critical

## 16. 🏁 Final Summary

This repo structure ensures:

- Scalability
- Maintainability
- Developer productivity
- Production readiness

## 17. 🔥 Final Thought

> A well-structured repo is the difference between:

- a demo project
  vs
- a real engineering system

