import json
from pathlib import Path
from typing import Any


def load_shared_chat_contract() -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[4]
    contract_path = repo_root / "packages" / "types" / "src" / "chat-contract.json"

    with contract_path.open("r", encoding="utf-8") as file:
        return json.load(file)


CHAT_CONTRACT = load_shared_chat_contract()
TRACE_EVENT_TYPES = set(CHAT_CONTRACT["traceEventTypes"])
TRACE_BRANCHES = set(CHAT_CONTRACT["traceBranches"])
TRACE_MODES = set(CHAT_CONTRACT["traceModes"])
CHAT_PROMPT_MIN_LENGTH = int(CHAT_CONTRACT["chatPrompt"]["minLength"])
CHAT_PROMPT_MAX_LENGTH = int(CHAT_CONTRACT["chatPrompt"]["maxLength"])
