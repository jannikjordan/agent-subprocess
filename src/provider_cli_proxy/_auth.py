import asyncio
import json
from pathlib import Path
from typing import Any

from ._models import Provider
from ._process import run_child
from ._providers import Failure, codex_config_options

_MAX_STATUS_BYTES = 65_536
_CODEX_PLANS = frozenset(
    (
        "go",
        "plus",
        "pro",
        "prolite",
        "promax",
        "team",
        "business",
        "self_serve_business_prolite",
        "enterprise",
        "ent26",
        "edu",
        "edu_plus",
        "edu_pro",
        "sci",
        "sci_plus",
    )
)
_CLAUDE_PLANS = frozenset(("pro", "max", "team", "enterprise", "ultra"))


def _unverified() -> Failure:
    return Failure(
        "auth_check_failed", "The provider CLI could not verify subscription sign-in."
    )


def _signed_out(provider: Provider) -> Failure:
    command = "codex login" if provider == "codex" else "claude auth login"
    return Failure("auth_required", f"Sign in with {command} and retry.")


def _subscription_required() -> Failure:
    return Failure(
        "subscription_required",
        "Sign in to the provider CLI with a supported subscription.",
    )


def _object(data: bytes | bytearray) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (ValueError, RecursionError):
        raise _unverified() from None
    if not isinstance(value, dict):
        raise _unverified()
    return value


def _subscription(plan: object, supported: frozenset[str]) -> bool:
    return isinstance(plan, str) and plan.casefold() in supported


def _rpc(*messages: dict[str, Any]) -> bytes:
    return b"".join(json.dumps(message).encode() + b"\n" for message in messages)


class _CodexAccountRead:
    initial = _rpc(
        {
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "provider_cli_proxy", "version": "0.1.0"}
            },
        }
    )

    def __init__(self) -> None:
        self.size = 0
        self.initialized = False
        self.verified = False

    def handle(self, record: bytes) -> bytes | None:
        self.size += len(record)
        if self.size > _MAX_STATUS_BYTES:
            raise _unverified()
        message = _object(record)
        if "method" in message and "id" not in message:
            return None
        request_id = message.get("id")
        result = message.get("result")
        if (
            type(request_id) is not int
            or not isinstance(result, dict)
            or "error" in message
        ):
            raise _unverified()
        if request_id == 1 and not self.initialized:
            self.initialized = True
            return _rpc(
                {"method": "initialized"},
                {"id": 2, "method": "account/read", "params": {"refreshToken": False}},
            )
        if request_id != 2 or not self.initialized or self.verified:
            raise _unverified()

        requires_auth = result.get("requiresOpenaiAuth")
        if type(requires_auth) is not bool or "account" not in result:
            raise _unverified()
        if not requires_auth:
            raise _subscription_required()
        account = result["account"]
        if account is None:
            raise _signed_out("codex")
        if not isinstance(account, dict) or not isinstance(account.get("type"), str):
            raise _unverified()
        if account["type"] != "chatgpt":
            raise _subscription_required()
        plan = account.get("planType")
        if not isinstance(plan, str):
            raise _unverified()
        if not _subscription(plan, _CODEX_PLANS):
            raise _subscription_required()
        self.verified = True
        return b""


async def check_subscription(
    provider: Provider,
    argv: tuple[str, ...],
    cwd: Path,
    stop: asyncio.Future[None],
    deadline: float,
) -> None:
    """Read the selected CLI's account status without sending a user prompt."""
    try:
        if provider == "codex":
            account = _CodexAccountRead()
            config = codex_config_options(
                cwd,
                "features.shell_tool=false",
                f"sqlite_home={json.dumps(str(cwd), ensure_ascii=False)}",
                f"log_dir={json.dumps(str(cwd), ensure_ascii=False)}",
            )
            code, _ = await run_child(
                [*argv, "app-server", "--listen", "stdio://", *config],
                cwd,
                account.initial,
                account.handle,
                stop,
                deadline,
                interactive=True,
            )
            if code != 0 or not account.verified:
                raise _unverified()
            return

        status = bytearray()

        def collect(record: bytes) -> None:
            if len(status) + len(record) > _MAX_STATUS_BYTES:
                raise _unverified()
            status.extend(record)

        exit_code, _ = await run_child(
            [*argv, "--safe-mode", "--restricted", "auth", "status", "--json"],
            cwd,
            b"",
            collect,
            stop,
            deadline,
        )
        data = _object(status)
        logged_in = data.get("loggedIn")
        if logged_in is False:
            raise _signed_out("claude")
        if logged_in is not True or exit_code != 0:
            raise _unverified()
        if (
            data.get("authMethod") != "claude.ai"
            or data.get("apiProvider") != "firstParty"
        ):
            raise _subscription_required()
        plan = data.get("subscriptionType")
        if not isinstance(plan, str):
            raise _unverified()
        if not _subscription(plan, _CLAUDE_PLANS):
            raise _subscription_required()
    except Failure as failure:
        if failure.error.code != "protocol_error":
            raise
        raise _unverified() from None
    except OSError:
        raise _unverified() from None
