from __future__ import annotations

from .skill_core import ExecutionUpdate, SkillResult


def build_analysis_detail(intent: str, sentiment: str, keywords: list[str], execution_mode: str, normalized_prompt: str) -> str:
    readable_keywords = ", ".join(keywords) if keywords else "none"
    return (
        "Processing the user's request.\n"
        f"Normalized content: {normalized_prompt}.\n"
        f"Detected intent: {intent}. Sentiment: {sentiment}.\n"
        f"Planned execution mode: {execution_mode}.\n"
        f"Analyzing key signals: {readable_keywords}."
    )


def build_plan_detail(nodes: list[ExecutionUpdate] | list[object], dag_summary: str) -> str:
    described_nodes: list[str] = []
    for index, node in enumerate(nodes, start=1):
        description = ""
        skill = "unknown"
        depends_on: list[str] = []
        if hasattr(node, "input"):
            description = str(getattr(node, "input", {}).get("description", "")).strip()
            skill = str(getattr(node, "skill", "unknown"))
            depends_on = list(getattr(node, "depends_on", []))
        node_label = f"Step {index}: {skill}"
        if description:
            node_label += f" for '{description}'"
        if depends_on:
            node_label += f" after completing {', '.join(depends_on)}"
        described_nodes.append(node_label)

    plan_lines = "\n".join(described_nodes) if described_nodes else dag_summary
    return (
        "Execution plan created.\n"
        f"Total DAG steps: {len(nodes)}.\n"
        f"Planned steps:\n{plan_lines}."
    )


def build_done_detail(total_nodes: int, successful_nodes: int, failed_nodes: int) -> str:
    return (
        "Execution completed.\n"
        f"Total steps: {total_nodes}. Successful: {successful_nodes}. Failed: {failed_nodes}.\n"
        "The final response has been synthesized and sent back to the user."
    )


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
        "data_points_count": str((result.metadata or {}).get("data_points_count", "0")),
        "data_coverage": str((result.metadata or {}).get("data_coverage", "0")),
        "conflict_count": str((result.metadata or {}).get("conflict_count", "0")),
        "evidence_quality": str((result.metadata or {}).get("evidence_quality", "n/a")),
        "task_description": str(update.node.input.get("description", "")).strip(),
        "output": result_preview[:220],
    }


def build_tool_call_detail(trace_entry: dict[str, str]) -> str:
    topic = trace_entry.get("task_description", "").strip() or trace_entry["node_id"]
    deps_text = trace_entry["depends_on"] if trace_entry["depends_on"] != "-" else "none"
    sources_text = trace_entry["source_count"]
    citations_text = trace_entry["citation_count"]
    confidence_text = trace_entry["confidence"] if trace_entry["confidence"] != "n/a" else "not available"
    freshness_text = trace_entry["freshness"] if trace_entry["freshness"] != "n/a" else "not available"
    fallback_text = "yes" if trace_entry["fallback_used"] == "true" else "no"
    skill_name = trace_entry["skill_name"]

    if skill_name == "research":
        opening = f"Searching for information about: {topic}."
        evidence_line = (
            f"Collected {sources_text} sources and {citations_text} citations. "
            f"Data freshness: {freshness_text}. Current confidence: {confidence_text}."
        )
    elif skill_name == "finance":
        opening = f"Fetching market data for: {topic}."
        evidence_line = (
            f"Checked {sources_text} data sources and recorded {citations_text} references. "
            f"Data freshness: {freshness_text}. Current confidence: {confidence_text}."
        )
    elif skill_name == "synthesizer":
        opening = "Synthesizing information from the collected sources."
        evidence_line = (
            f"This step is using {sources_text} sources and {citations_text} citations to generate the final answer. "
            f"Current synthesis confidence: {confidence_text}."
        )
    elif skill_name == "analysis":
        opening = f"Running reasoning for: {topic}."
        evidence_line = (
            f"Reasoning is using {trace_entry['data_points_count']} data points, data coverage {trace_entry['data_coverage']}, "
            f"data conflicts: {trace_entry['conflict_count']}, evidence quality: {trace_entry['evidence_quality']}, "
            f"current confidence: {confidence_text}."
        )
    else:
        opening = f"Processing step '{skill_name}' for: {topic}."
        evidence_line = (
            f"Available sources: {sources_text}. Citations: {citations_text}. "
            f"Freshness: {freshness_text}. Confidence: {confidence_text}."
        )

    summary_lines = [
        opening,
        f"Dependencies required before this step: {deps_text}. Branch: {trace_entry['branch']}. Priority: {trace_entry['priority']}.",
        f"Tool/provider in use: {trace_entry['provider']}. Route score: {trace_entry['route_score']}.",
        evidence_line,
        (
            f"Executed in {trace_entry['duration_ms']} ms, attempts: {trace_entry['attempts']}, "
            f"cache_hit={trace_entry['cache_hit']}, fallback_used={fallback_text}, error_type={trace_entry['error_type']}."
        ),
    ]

    if trace_entry["used_tool"] != "none":
        summary_lines.append(f"Selected tool for this step: {trace_entry['used_tool']}.")
    if trace_entry["providers_tried"] != "none":
        summary_lines.append(f"Providers tried: {trace_entry['providers_tried']}.")
    if trace_entry["citations"] != "none":
        summary_lines.append(f"Reference/evidence URLs in use: {trace_entry['citations']}.")

    return "\n".join(summary_lines)


def build_tool_result_detail(trace_entry: dict[str, str]) -> str:
    outcome = "succeeded" if trace_entry["success"] == "true" else "failed"
    return (
        f"Step {trace_entry['node_id']} {outcome}. "
        f"The result payload was recorded in runtime state for skill '{trace_entry['skill_name']}'."
    )


def build_tool_phase_details(trace_entry: dict[str, str]) -> list[str]:
    skill_name = trace_entry["skill_name"]
    source_count = trace_entry.get("source_count", "0")
    citation_count = trace_entry.get("citation_count", "0")
    providers = trace_entry.get("providers_tried", "none")
    topic = trace_entry.get("task_description", "").strip() or trace_entry["node_id"]
    is_success = trace_entry.get("success") == "true"

    if skill_name == "research":
        phases = [
            f"Sending a research query for '{topic}' to the relevant sources.",
        ]
        if is_success:
            phases.append(
                f"Received initial data from {source_count} sources. Extracting main points and supporting evidence."
            )
            phases.append(
                f"Comparing {citation_count} citations and evaluating confidence before moving to synthesis."
            )
        else:
            phases.append(
                "No sufficient evidence was found. This step is being marked as lacking data or relevance."
            )
        return phases

    if skill_name == "finance":
        phases = [
            f"Querying the market data source chain for '{topic}'.",
        ]
        if providers != "none":
            phases.append(f"Providers being compared sequentially or in parallel: {providers}.")
        if is_success:
            phases.append(
                f"Received data from {source_count} sources. Normalizing price, timestamp, and confidence."
            )
        else:
            phases.append("Live pricing sources did not return enough data. Marking the result as degraded and retaining reference sources.")
        return phases

    if skill_name == "analysis":
        phases = [
            f"Collecting research signals for '{topic}' and normalizing them into quantitative data points.",
            (
                f"Evaluating data coverage ({trace_entry.get('data_coverage', '0')}), "
                f"evidence quality ({trace_entry.get('evidence_quality', 'n/a')}) and conflicts ({trace_entry.get('conflict_count', '0')})."
            ),
        ]
        if is_success:
            phases.append("Created a provisional conclusion with assumptions and limits for the final synthesis step.")
        else:
            phases.append("Reasoning could not proceed because earlier steps did not provide valid evidence.")
        return phases

    if skill_name == "synthesizer":
        phases = [
            "Collecting all intermediate results and preparing the final answer.",
            f"Cross-checking {citation_count} citations, inspecting source conflicts, and organizing the argument.",
        ]
        if is_success:
            phases.append("Finalizing the conclusion, including confidence level and remaining limitations.")
        else:
            phases.append("There are not enough reliable intermediate results to synthesize. The system will return an insufficient-evidence status.")
        return phases

    return [
        f"Executing step '{skill_name}' for '{topic}'.",
        "Checking the result and preparing to move to the next step.",
    ]
