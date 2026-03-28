from src.glass_box_chat.services.runtime_metrics import RuntimeMetrics


def test_runtime_metrics_records_trace() -> None:
    metrics = RuntimeMetrics(llm_provider="mock")
    metrics.mark_run_started(execution_mode="parallel", dag_node_count=3)

    metrics.record_execution_trace(
        [
            {
                "node_id": "n1",
                "cache_hit": "true",
                "duration_ms": "120",
                "attempts": "1",
                "route_score": "0.9",
                "output": "ok",
            },
            {
                "node_id": "n2",
                "cache_hit": "false",
                "duration_ms": "260",
                "attempts": "2",
                "route_score": "fallback",
                "output": "timeout",
            },
        ]
    )

    metrics.mark_completed()
    state = metrics.state

    assert state["total_runs"] == 1
    assert state["total_nodes_executed"] == 2
    assert state["cache_hits"] == 1
    assert state["cache_misses"] == 1
    assert state["timeouts"] == 1
    assert state["retries"] == 1
    assert state["fallback_routes"] == 1
    assert state["avg_node_duration_ms"] == 190
    assert isinstance(state["last_completed_at"], str)


def test_runtime_metrics_snapshot_with_breakers() -> None:
    metrics = RuntimeMetrics(llm_provider="gemini")
    snapshot = metrics.snapshot_with_breakers(
        breaker_states={"research": False, "synthesizer": True},
        breaker_details={"synthesizer": {"state": "open", "consecutive_failures": 5}},
    )

    assert snapshot["llm_provider"] == "gemini"
    assert snapshot["breaker_states"]["synthesizer"] is True
    assert snapshot["breaker_details"]["synthesizer"]["state"] == "open"
