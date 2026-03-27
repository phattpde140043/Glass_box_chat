from glass_box_chat.main import build_greeting


def test_build_greeting() -> None:
    assert "Glass Box AI Chat" in build_greeting()
