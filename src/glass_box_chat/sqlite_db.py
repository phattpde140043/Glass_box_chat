from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DATABASE_DIR = REPO_ROOT / "data"
DATABASE_PATH = DATABASE_DIR / "glassbox.db"

TASK_STATE_CREATED = "CREATED"
TASK_STATE_QUEUED = "QUEUED"
TASK_STATE_RUNNING = "RUNNING"
TASK_STATE_WAITING = "WAITING"
TASK_STATE_COMPLETED = "COMPLETED"
TASK_STATE_FAILED = "FAILED"

TASK_STATE_TRANSITIONS: dict[str, set[str]] = {
    TASK_STATE_CREATED: {TASK_STATE_QUEUED},
    TASK_STATE_QUEUED: {TASK_STATE_RUNNING},
    TASK_STATE_RUNNING: {TASK_STATE_WAITING, TASK_STATE_COMPLETED, TASK_STATE_FAILED},
    TASK_STATE_WAITING: {TASK_STATE_RUNNING},
    TASK_STATE_FAILED: {TASK_STATE_QUEUED},
    TASK_STATE_COMPLETED: set(),
}


def get_database_path() -> Path:
    return DATABASE_PATH


def initialize_sqlite() -> Path:
    """Create SQLite database and baseline runtime tables for portfolio deployment."""
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA foreign_keys=ON;")

        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runtime_sessions (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                label TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runtime_tasks (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                tenant_id TEXT,
                agent_id TEXT NOT NULL,
                parent_task_id TEXT,
                task_type TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'normal',
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                dedupe_key TEXT,
                scheduled_at TEXT,
                started_at TEXT,
                finished_at TEXT,
                locked_by TEXT,
                locked_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES runtime_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_task_id) REFERENCES runtime_tasks(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_runtime_tasks_queue
            ON runtime_tasks(status, priority, scheduled_at, created_at);

            CREATE INDEX IF NOT EXISTS idx_runtime_tasks_session
            ON runtime_tasks(session_id, created_at);

            CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_tasks_dedupe
            ON runtime_tasks(dedupe_key)
            WHERE dedupe_key IS NOT NULL;

            CREATE TABLE IF NOT EXISTS runtime_events (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                task_id TEXT,
                agent_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES runtime_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES runtime_tasks(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_runtime_events_session
            ON runtime_events(session_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_runtime_events_task
            ON runtime_events(task_id, created_at);

            CREATE TABLE IF NOT EXISTS runtime_hitl_waiting (
                task_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                question TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                resumed_at TEXT,
                answer TEXT,
                status TEXT NOT NULL DEFAULT 'waiting',
                FOREIGN KEY (task_id) REFERENCES runtime_tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (session_id) REFERENCES runtime_sessions(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_runtime_hitl_waiting_session
            ON runtime_hitl_waiting(session_id, requested_at);
            """
        )

    return DATABASE_PATH


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("PRAGMA foreign_keys=ON;")
    return connection


def count_runtime_sessions() -> int:
    with _connect() as connection:
        row = connection.execute("SELECT COUNT(*) FROM runtime_sessions;").fetchone()
    return int(row[0]) if row else 0


def create_runtime_session(session_id: str, label: str, tenant_id: str | None = None) -> None:
    now = utc_now_iso()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO runtime_sessions (id, tenant_id, label, status, created_at, updated_at)
            VALUES (?, ?, ?, 'running', ?, ?)
            """,
            (session_id, tenant_id, label, now, now),
        )


def create_root_task(task_id: str, session_id: str, prompt: str, agent_id: str = "CoordinatorAgent") -> None:
    now = utc_now_iso()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO runtime_tasks (
                id,
                session_id,
                tenant_id,
                agent_id,
                parent_task_id,
                task_type,
                priority,
                status,
                payload_json,
                attempts,
                max_attempts,
                dedupe_key,
                scheduled_at,
                started_at,
                finished_at,
                locked_by,
                locked_at,
                last_error,
                created_at,
                updated_at
            )
            VALUES (?, ?, NULL, ?, NULL, 'agent', 'normal', ?, ?, 0, 3, NULL, ?, NULL, NULL, NULL, NULL, NULL, ?, ?)
            """,
            (
                task_id,
                session_id,
                agent_id,
                TASK_STATE_CREATED,
                json.dumps({"prompt": prompt}, ensure_ascii=True),
                now,
                now,
                now,
            ),
        )


def append_runtime_event(
    event_id: str,
    session_id: str,
    task_id: str | None,
    agent_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO runtime_events (id, session_id, task_id, agent_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                session_id,
                task_id,
                agent_id,
                event_type,
                json.dumps(payload, ensure_ascii=True),
                utc_now_iso(),
            ),
        )


def complete_runtime_task(task_id: str, status: str, last_error: str | None = None) -> None:
    now = utc_now_iso()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE runtime_tasks
            SET status = ?, finished_at = ?, last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, now, last_error, now, task_id),
        )


def get_task_status(task_id: str) -> str | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT status FROM runtime_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
    if not row:
        return None
    return str(row[0])


def transition_runtime_task(task_id: str, target_status: str) -> None:
    current_status = get_task_status(task_id)
    if current_status is None:
        raise ValueError(f"Task not found: {task_id}")

    allowed = TASK_STATE_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise ValueError(f"Invalid task transition: {current_status} -> {target_status}")

    now = utc_now_iso()
    started_at = now if target_status == TASK_STATE_RUNNING else None
    finished_at = now if target_status in {TASK_STATE_COMPLETED, TASK_STATE_FAILED} else None

    with _connect() as connection:
        connection.execute(
            """
            UPDATE runtime_tasks
            SET status = ?,
                started_at = COALESCE(?, started_at),
                finished_at = COALESCE(?, finished_at),
                updated_at = ?
            WHERE id = ?
            """,
            (target_status, started_at, finished_at, now, task_id),
        )


def complete_runtime_session(session_id: str, status: str) -> None:
    now = utc_now_iso()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE runtime_sessions
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, now, session_id),
        )


def list_runtime_sessions(limit: int = 20) -> list[dict[str, str | None]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, tenant_id, label, status, created_at, updated_at
            FROM runtime_sessions
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "id": str(row[0]),
            "tenantId": row[1],
            "label": str(row[2]),
            "status": str(row[3]),
            "createdAt": str(row[4]),
            "updatedAt": str(row[5]),
        }
        for row in rows
    ]


def list_runtime_tasks_by_session(session_id: str) -> list[dict[str, str | int | None]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, agent_id, parent_task_id, task_type, priority, status,
                   attempts, max_attempts, scheduled_at, started_at, finished_at,
                   last_error, created_at, updated_at
            FROM runtime_tasks
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        ).fetchall()

    return [
        {
            "id": str(row[0]),
            "agentId": str(row[1]),
            "parentTaskId": row[2],
            "taskType": str(row[3]),
            "priority": str(row[4]),
            "status": str(row[5]),
            "attempts": int(row[6]),
            "maxAttempts": int(row[7]),
            "scheduledAt": row[8],
            "startedAt": row[9],
            "finishedAt": row[10],
            "lastError": row[11],
            "createdAt": str(row[12]),
            "updatedAt": str(row[13]),
        }
        for row in rows
    ]


def count_runtime_tasks_by_session(session_id: str) -> int:
    with _connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM runtime_tasks WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def list_runtime_events_by_session(
    session_id: str,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, str | None]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, task_id, agent_id, event_type, payload_json, created_at
            FROM runtime_events
            WHERE session_id = ?
            ORDER BY created_at ASC
            LIMIT ?
            OFFSET ?
            """,
            (session_id, limit, offset),
        ).fetchall()

    return [
        {
            "id": str(row[0]),
            "taskId": row[1],
            "agentId": str(row[2]),
            "eventType": str(row[3]),
            "payload": row[4],
            "createdAt": str(row[5]),
        }
        for row in rows
    ]


def count_runtime_events_by_session(session_id: str) -> int:
    with _connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM runtime_events WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def create_hitl_waiting(task_id: str, session_id: str, agent_id: str, question: str) -> None:
    now = utc_now_iso()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO runtime_hitl_waiting (
                task_id,
                session_id,
                agent_id,
                question,
                requested_at,
                resumed_at,
                answer,
                status
            )
            VALUES (?, ?, ?, ?, ?, NULL, NULL, 'waiting')
            ON CONFLICT(task_id) DO UPDATE SET
                question = excluded.question,
                requested_at = excluded.requested_at,
                resumed_at = NULL,
                answer = NULL,
                status = 'waiting'
            """,
            (task_id, session_id, agent_id, question, now),
        )


def get_waiting_task_by_agent(agent_id: str) -> dict[str, str] | None:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT task_id, session_id
            FROM runtime_hitl_waiting
            WHERE agent_id = ? AND status = 'waiting'
            ORDER BY requested_at DESC
            LIMIT 1
            """,
            (agent_id,),
        ).fetchone()

    if not row:
        return None

    return {
        "taskId": str(row[0]),
        "sessionId": str(row[1]),
    }


def resolve_hitl_waiting(task_id: str, answer: str) -> None:
    now = utc_now_iso()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE runtime_hitl_waiting
            SET answer = ?, resumed_at = ?, status = 'resumed'
            WHERE task_id = ?
            """,
            (answer, now, task_id),
        )
