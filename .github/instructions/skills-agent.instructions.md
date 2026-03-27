---
description: Describe when these instructions should be loaded by the agent based on task context
# applyTo: 'Describe when these instructions should be loaded by the agent based on task context' # when provided, instructions will automatically be added to the request context when the pattern matches an attached file
---

<!-- Tip: Use /create-instructions in chat to generate content with agent assistance -->

Dưới đây là file `.md` bạn có thể dùng trực tiếp trong repo — mình đã **chuẩn hóa theo mindset SDK + production**, nhưng vẫn giữ insight từ bài viết bạn đưa 👇

---

````md
# 🧩 Skill Agent Specification (SDK-Oriented Design)

## 1. Overview

A **Skill Agent** is not just a prompt or a markdown file.

> It is a **self-contained capability package** that includes instructions, data, tools, and execution logic that an AI system can dynamically discover and use.

In a modern Agent SDK architecture, a Skill represents:

- A **domain-specific capability**
- A **reusable execution unit**
- A **context-efficient knowledge container**

---

## 2. Core Concept

### ❌ Common Misconception

> "A skill is just a markdown file with instructions"

This is **incorrect**.

---

### ✅ Correct Definition

A Skill is:

```text
A structured folder that contains everything an agent needs to perform a task.
````

---

### 📦 Skill = Knowledge Package

A Skill may include:

* Instructions (markdown)
* Scripts (code execution)
* References (API docs, examples)
* Assets (templates, files)
* Config (setup, credentials)
* Memory (logs, state)

---

## 3. Progressive Disclosure Architecture

Modern Agent SDKs (e.g., Claude-style systems) use a **layered loading strategy** to optimize context usage.

---

### 🧠 Layer 1 – Metadata (Discovery Phase)

```json
{
  "name": "search-web",
  "description": "Use this skill when the user asks for up-to-date or external information."
}
```

#### Purpose:

* Used by Orchestrator to **decide whether to activate the skill**
* Must act as a **trigger condition**, not just a summary

#### Key Insight:

> Description is written for the **model**, not humans.

---

### 📄 Layer 2 – Skill Instructions (`SKILL.md`)

Loaded only when the skill is activated.

Contains:

* Task instructions
* Execution guidelines
* Gotchas
* Usage examples

#### Best Practices:

* Keep under ~500 lines
* Focus on **non-obvious knowledge**
* Avoid repeating what the model already knows

---

### 📂 Layer 3 – References / Scripts / Assets

Loaded **on demand only when needed**

Examples:

* `references/api.md`
* `scripts/fetch-data.ts`
* `assets/template.md`

#### Key Benefit:

> Zero token cost until accessed

---

## 4. Standard Skill Structure

```bash
skill-name/
│
├── skill.json           # Metadata (name, description, triggers)
├── SKILL.md             # Main instructions
│
├── references/          # Docs, API usage, examples
│   └── api.md
│
├── scripts/             # Executable logic
│   └── run.ts
│
├── assets/              # Templates, output formats
│   └── template.md
│
├── config.json          # User-specific setup
├── memory/              # Logs or persistent state
│   └── history.log
```

---

## 5. Key Components Explained

---

### 5.1 Metadata (`skill.json`)

#### Definition:

Describes when and why a skill should be used.

#### Example:

```json
{
  "name": "data-analysis",
  "description": "Use this skill when the user asks for data analysis, metrics, or insights from structured data.",
  "triggers": ["analyze", "metrics", "report"]
}
```

#### Implementation Notes:

* Used by **Orchestrator for routing**
* Should include **clear activation signals**
* Can include examples for higher activation accuracy

---

### 5.2 Instruction File (`SKILL.md`)

#### Definition:

Guides the agent on how to perform the task.

#### Should include:

* Task overview
* Step-by-step reasoning
* Constraints
* Gotchas (critical!)

---

#### Example:

```md
## Steps

1. Identify the dataset
2. Extract key metrics
3. Generate summary

## Gotchas

- Data may contain null values
- Avoid averaging percentages directly
```

---

### 5.3 References

#### Definition:

Supplementary knowledge not included in the main instruction.

#### Example:

```md
# API Usage

GET /metrics
POST /analyze
```

#### Purpose:

* Reduce clutter in main instruction
* Allow **on-demand retrieval**

---

### 5.4 Scripts

#### Definition:

Executable code the agent can use.

#### Example:

```ts
export async function fetchData() {
  return await fetch("/api/data").then(res => res.json())
}
```

#### Key Insight:

> Providing scripts is more powerful than describing logic.

---

### 5.5 Assets

#### Definition:

Reusable output templates or files.

#### Example:

```md
# Report Template

## Summary
...

## Insights
...
```

---

### 5.6 Config

#### Definition:

Stores user-specific setup.

#### Example:

```json
{
  "apiKey": "user-key",
  "workspaceId": "123"
}
```

#### Pattern:

* If missing → ask user
* Persist for reuse

---

### 5.7 Memory

#### Definition:

Persistent data generated by the skill.

#### Examples:

* Logs
* Previous outputs
* Historical context

#### Important Note:

* Should be stored in a **stable directory**
* Avoid losing data during upgrades

---

## 6. Skill Execution Flow

```text
User Input
     ↓
Orchestrator
     ↓
Skill Discovery (Metadata scan)
     ↓
Skill Activation
     ↓
Load SKILL.md
     ↓
Load references/scripts (if needed)
     ↓
Execute
     ↓
Return Result
```

---

## 7. Skill Categories (Industry Patterns)

Common types of skills:

1. Library / API Reference
2. Product Verification
3. Data Fetching & Analysis
4. Business Automation
5. Code Scaffolding
6. Code Review & Quality
7. CI/CD & Deployment
8. Runbooks (incident handling)
9. Infrastructure Operations

---

## 8. Best Practices

---

### ✅ Focus on Non-Obvious Knowledge

Do NOT include:

* basic programming concepts
* generic explanations

---

### ✅ Add "Gotchas"

This is the most valuable section.

```md
## Gotchas

- API rate limit is 10 req/sec
- This endpoint returns stale data after caching
```

---

### ✅ Use File System as Context

* Keep instructions minimal
* Move details into references/scripts

---

### ✅ Avoid Over-Constraining

Do not "railroad" the agent.

Allow flexibility in execution.

---

### ✅ Support Setup Flow

* Detect missing config
* Ask user dynamically

---

### ✅ Optimize Description for Triggering

Bad:

> "This skill analyzes data"

Good:

> "Use this skill when the user asks for metrics, reports, dashboards, or data insights"

---

### ✅ Store and Reuse Memory

* Save outputs
* Compare with previous runs
* Maintain consistency

---

## 9. Key Insight

> **Context Engineering > Prompt Engineering**

A well-designed Skill system:

* reduces token usage
* improves reasoning quality
* enables modular AI systems

---

## 10. Summary

A Skill Agent is:

* Not a prompt
* Not a markdown file
* Not just instructions

It is:

> ✅ A modular, discoverable, executable capability unit
> ✅ Designed for scalability, reuse, and efficiency
> ✅ The foundation of modern multi-agent systems


