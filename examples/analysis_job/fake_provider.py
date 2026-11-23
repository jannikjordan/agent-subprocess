"""Act as either official executable for the offline example."""

import json
import sys

ANSWER = "18 tickets closed. Wednesday had the highest count with 9."
SESSION = "00000000-0000-4000-8000-000000000001"


def account_status(provider: str) -> bool:
    """Answer the CLI subscription preflight using synthetic data."""
    if provider == "codex" and sys.argv[2:3] == ["app-server"]:
        initialize = json.loads(sys.stdin.readline())
        print(json.dumps({"id": initialize["id"], "result": {}}), flush=True)
        assert json.loads(sys.stdin.readline())["method"] == "initialized"
        request = json.loads(sys.stdin.readline())
        assert request["method"] == "account/read"
        print(
            json.dumps(
                {
                    "id": request["id"],
                    "result": {
                        "account": {"type": "chatgpt", "planType": "pro"},
                        "requiresOpenaiAuth": True,
                    },
                }
            ),
            flush=True,
        )
        assert not sys.stdin.read()
        return True
    if provider == "claude" and sys.argv[-3:] == ["auth", "status", "--json"]:
        print(
            json.dumps(
                {
                    "loggedIn": True,
                    "authMethod": "claude.ai",
                    "apiProvider": "firstParty",
                    "subscriptionType": "max",
                }
            )
        )
        return True
    return False


def emit(kind: str, **fields: object) -> None:
    """Write one JSON Lines record to the proxy."""
    print(json.dumps({"type": kind, **fields}), flush=True)


def codex() -> None:
    """Emit a completed Codex turn."""
    emit("thread.started", thread_id=SESSION)
    emit("turn.started")
    emit(
        "item.completed", item={"id": "item_1", "type": "agent_message", "text": ANSWER}
    )
    emit("turn.completed", usage={"input_tokens": 20, "output_tokens": 12})


def claude() -> None:
    """Emit a Claude response in chunks followed by the final result."""
    emit(
        "system",
        subtype="init",
        session_id=SESSION,
        model="fixture-claude",
        tools=[],
        mcp_servers=[],
    )
    for chunk in ("18 tickets closed. ", "Wednesday had the highest count with 9."):
        emit(
            "stream_event",
            parent_tool_use_id=None,
            event={
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": chunk},
            },
        )
    emit("result", subtype="success", is_error=False, result=ANSWER, session_id=SESSION)


def main() -> int:
    """Verify prompt delivery before emitting the fixture answer."""
    if len(sys.argv) < 2:
        return 2
    provider = sys.argv[1]
    if provider not in {"codex", "claude"}:
        return 2
    if "--version" in sys.argv:
        print("codex-cli 0.171.0" if provider == "codex" else "2.1.330 (Claude Code)")
        return 0
    if account_status(provider):
        return 0
    prompt = sys.stdin.buffer.read().decode("utf-8")
    if "Monday,3" not in prompt or "Wednesday,9" not in prompt:
        print("Expected the synthetic ticket counts on stdin.", file=sys.stderr)
        return 1
    if provider == "codex":
        codex()
    else:
        claude()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
