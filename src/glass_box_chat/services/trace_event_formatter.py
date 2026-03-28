from __future__ import annotations

from .skill_core import ExecutionUpdate, SkillResult


def build_execution_trace_entry(update: ExecutionUpdate, result: SkillResult, result_preview: str) -> dict[str, str]:
    return {
        "node_id": update.node.id,
        "skill_name": update.skill_name,
        "branch": update.node.branch,
        "depends_on": ",".join(update.node.depends_on) if update.node.depends_on else "-",
        "route_score": str(update.node.input.get("route_score", "n/a")),
        "success": "true" if result.success else "false",
        "duration_ms": str((result.metadata or {}).get("duration_ms", "n/a")),
        "cache_hit": "true" if (result.metadata or {}).get("cache_hit") else "false",
        "attempts": str((result.metadata or {}).get("attempts", "n/a")),
        "priority": str(update.node.priority),
        "error_type": str((result.metadata or {}).get("error_type", "none")),
        "provider": str((result.metadata or {}).get("provider", "n/a")),
        "source_count": str((result.metadata or {}).get("source_count", "0")),
        "citation_count": str((result.metadata or {}).get("citation_count", "0")),
        "citations": str((result.metadata or {}).get("citations", "none")),
        "freshness": str((result.metadata or {}).get("freshness", "n/a")),
        "fallback_used": "true" if (result.metadata or {}).get("fallback_used") else "false",
        "confidence": str((result.metadata or {}).get("confidence", "n/a")),
        "intent": str((result.metadata or {}).get("intent", "n/a")),
        "providers_tried": str((result.metadata or {}).get("providers_tried", "none")),
        "cache_ttl_seconds": str((result.metadata or {}).get("cache_ttl_seconds", "n/a")),
        "used_tool": str((result.metadata or {}).get("used_tool", "none")),
        "output": result_preview[:220],
    }


def build_tool_call_detail(trace_entry: dict[str, str]) -> str:
    return (
        f"node={trace_entry['node_id']} skill={trace_entry['skill_name']} deps={trace_entry['depends_on']} "
        f"score={trace_entry['route_score']} priority={trace_entry['priority']} "
        f"cache_hit={trace_entry['cache_hit']} duration_ms={trace_entry['duration_ms']} "
        f"attempts={trace_entry['attempts']} error_type={trace_entry['error_type']} "
        f"provider={trace_entry['provider']} source_count={trace_entry['source_count']} "
        f"citation_count={trace_entry['citation_count']} freshness={trace_entry['freshness']} "
        f"fallback_used={trace_entry['fallback_used']} confidence={trace_entry['confidence']} "
        f"intent={trace_entry['intent']} providers_tried={trace_entry['providers_tried']} "
        f"cache_ttl_seconds={trace_entry['cache_ttl_seconds']} used_tool={trace_entry['used_tool']} "
        f"citations={trace_entry['citations']}"
    )


def build_tool_result_detail(trace_entry: dict[str, str]) -> str:
    return f"node={trace_entry['node_id']} success={trace_entry['success']} result={trace_entry['output']}"
