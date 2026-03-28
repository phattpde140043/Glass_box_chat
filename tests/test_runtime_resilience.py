from src.glass_box_chat.services.runtime_resilience import CircuitBreaker, NodeCache, ShortTermMemoryStore, classify_error


class DummyNode:
    def __init__(self) -> None:
        self.skill = "research"
        self.input = {"description": "weather today"}


def test_node_cache_set_get_and_expire_behavior() -> None:
    cache = NodeCache(ttl_seconds=60.0, version="v1")
    node = DummyNode()

    key = cache.build_key(
        node=node,
        normalized_prompt="weather in da nang",
        dependency_outputs={"task-1": "ok"},
        recent_memory="none",
    )

    cache.set(key, {"summary": "sunny"})
    value = cache.get(key)

    assert isinstance(value, dict)
    assert value.get("summary") == "sunny"


def test_circuit_breaker_open_and_recovery_flow() -> None:
    breaker = CircuitBreaker(fail_threshold=2, recovery_timeout_seconds=0.01, half_open_max_calls=1)

    assert breaker.allow_request() is True
    breaker.record_failure()
    breaker.record_failure()

    assert breaker.is_open() is True

    # Cannot pass immediately while open.
    assert breaker.allow_request() is False


def test_short_term_memory_store_limits_entries() -> None:
    memory = ShortTermMemoryStore(max_entries=2)
    session_id = "sess-1"

    memory.remember(session_id, "analysis", "first")
    memory.remember(session_id, "analysis", "second")
    memory.remember(session_id, "analysis", "third")

    snapshot = memory.snapshot(session_id, limit=5)

    assert memory.size(session_id) == 2
    assert "first" not in snapshot
    assert "second" in snapshot
    assert "third" in snapshot


def test_classify_error_categories() -> None:
    assert classify_error("timeout while calling provider") == "transient"
    assert classify_error("invalid schema payload") == "permanent"
    assert classify_error("unexpected crash") == "system"
