from glass_box_chat.main import app


def test_app_metadata() -> None:
    assert app.title == "The Glass Box API"
    assert app.version == "0.1.0"


def test_runtime_routes_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/run" in paths
    assert "/runtime/metrics" in paths
