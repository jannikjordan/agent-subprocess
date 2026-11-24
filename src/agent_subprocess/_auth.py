import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from ._models import Provider, RateLimitKind, RateLimitWindow
from ._process import run_child
from ._providers import Failure, claude_command_options, codex_config_options

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
_WINDOW_MINUTES: dict[RateLimitKind, int] = {"session": 300, "weekly": 10_080}


@dataclass(frozen=True, slots=True)
class _Subscription:
    plan: str
    limits: tuple[RateLimitWindow, ...] = ()


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


def _window(
    kind: RateLimitKind, percent: object, reset: datetime | None
) -> RateLimitWindow | None:
    if type(percent) not in (int, float) or not 0 <= percent <= 100:
        return None
    return RateLimitWindow(kind, float(percent), reset, _WINDOW_MINUTES[kind])


def _timestamp(value: object) -> datetime | None:
    if type(value) is not int or value < 0:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _iso_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value)
        return timestamp.astimezone(timezone.utc) if timestamp.tzinfo else None
    except (OSError, OverflowError, ValueError):
        return None


def _codex_limits(result: dict[str, Any]) -> tuple[RateLimitWindow, ...]:
    buckets = result.get("rateLimitsByLimitId")
    bucket = buckets.get("codex") if isinstance(buckets, dict) else None
    if not isinstance(bucket, dict):
        bucket = result.get("rateLimits")
        if not isinstance(bucket, dict) or bucket.get("limitId") != "codex":
            return ()
    limits: dict[RateLimitKind, RateLimitWindow] = {}
    for key in ("primary", "secondary"):
        row = bucket.get(key)
        if isinstance(row, dict):
            duration = row.get("windowDurationMins")
            for kind, minutes in _WINDOW_MINUTES.items():
                if duration == minutes and (
                    window := _window(
                        kind, row.get("usedPercent"), _timestamp(row.get("resetsAt"))
                    )
                ):
                    limits.setdefault(kind, window)
    return tuple(limits[kind] for kind in _WINDOW_MINUTES if kind in limits)


def _claude_limits(result: dict[str, Any]) -> tuple[RateLimitWindow, ...]:
    usage = result.get("rate_limits")
    if result.get("rate_limits_available") is not True or not isinstance(usage, dict):
        return ()
    limits: dict[RateLimitKind, RateLimitWindow] = {}
    reported_kinds: dict[RateLimitKind, tuple[str, str]] = {
        "session": ("five_hour", "session"),
        "weekly": ("seven_day", "weekly_all"),
    }
    for kind, (key, _) in reported_kinds.items():
        row = usage.get(key)
        if isinstance(row, dict) and (
            window := _window(
                kind, row.get("utilization"), _iso_timestamp(row.get("resets_at"))
            )
        ):
            limits[kind] = window
    rows = usage.get("limits")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            for kind, (_, reported_kind) in reported_kinds.items():
                if row.get("kind") == reported_kind and (
                    window := _window(
                        kind, row.get("percent"), _iso_timestamp(row.get("resets_at"))
                    )
                ):
                    limits.setdefault(kind, window)
    return tuple(limits[kind] for kind in _WINDOW_MINUTES if kind in limits)


def _control(request_id: str, **request: Any) -> bytes:
    return _rpc(
        {"type": "control_request", "request_id": request_id, "request": request}
    )


class _ClaudeUsageRead:
    initial = _control("initialize", subtype="initialize")

    def __init__(self) -> None:
        self.size = 0
        self.initialized = False
        self.limits: tuple[RateLimitWindow, ...] = ()

    def handle(self, record: bytes) -> bytes | None:
        self.size += len(record)
        if self.size > _MAX_STATUS_BYTES:
            raise _unverified()
        message = _object(record)
        if message.get("type") != "control_response":
            return None
        response = message.get("response")
        if not isinstance(response, dict) or response.get("subtype") != "success":
            raise _unverified()
        request_id = response.get("request_id")
        result = response.get("response")
        if not isinstance(result, dict):
            raise _unverified()
        if request_id == "initialize" and not self.initialized:
            self.initialized = True
            return _control("usage", subtype="get_usage", skip_behaviors=True)
        if request_id != "usage" or not self.initialized:
            raise _unverified()
        self.limits = _claude_limits(result)
        return b""


class _CodexAccountRead:
    def __init__(self, include_usage: bool) -> None:
        try:
            package_version = version("agent-subprocess")
        except PackageNotFoundError:
            package_version = "0.0.0"
        self.initial = _rpc(
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {
                        "name": "agent_subprocess",
                        "version": package_version,
                    }
                },
            }
        )
        self.size = 0
        self.initialized = False
        self.include_usage = include_usage
        self.plan: str | None = None
        self.limits: tuple[RateLimitWindow, ...] = ()

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
        if request_id == 3 and self.plan is not None and self.include_usage:
            self.limits = _codex_limits(result)
            return b""
        if request_id != 2 or not self.initialized or self.plan is not None:
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
        self.plan = plan.casefold()
        if self.include_usage:
            return _rpc({"id": 3, "method": "account/rateLimits/read"})
        return b""


async def _run_control_probe(
    argv: list[str],
    cwd: Path,
    initial: bytes,
    handle: Callable[[bytes], bytes | None],
    stop: asyncio.Future[None],
    deadline: float,
) -> int:
    rejection: Failure | None = None

    def reply(record: bytes) -> bytes | None:
        nonlocal rejection
        if rejection is not None:
            return None
        try:
            return handle(record)
        except Failure as error:
            # Closing stdin lets the child release its cwd before the probe directory is removed.
            rejection = error
            return b""

    code, _ = await run_child(
        argv, cwd, initial, reply, stop, deadline, interactive=True
    )
    if rejection is not None:
        raise rejection
    return code


async def check_subscription(
    provider: Provider,
    argv: tuple[str, ...],
    cwd: Path,
    stop: asyncio.Future[None],
    deadline: float,
    *,
    include_usage: bool = False,
) -> _Subscription:
    """Read the selected CLI's account status without sending a user prompt."""
    try:
        if provider == "codex":
            account = _CodexAccountRead(include_usage)
            config = codex_config_options(
                cwd,
                "features.shell_tool=false",
                f"sqlite_home={json.dumps(str(cwd), ensure_ascii=False)}",
                f"log_dir={json.dumps(str(cwd), ensure_ascii=False)}",
            )
            try:
                code = await _run_control_probe(
                    [*argv, "app-server", "--listen", "stdio://", *config],
                    cwd,
                    account.initial,
                    account.handle,
                    stop,
                    deadline,
                )
            except (Failure, OSError) as failure:
                if isinstance(failure, Failure) and failure.error.code == "cancelled":
                    raise
                if account.plan is None or not include_usage:
                    raise
                return _Subscription(account.plan)
            if account.plan is None or (code != 0 and not include_usage):
                raise _unverified()
            return _Subscription(account.plan, account.limits if code == 0 else ())

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
        limits: tuple[RateLimitWindow, ...] = ()
        if include_usage:
            probe = _ClaudeUsageRead()
            try:
                options = claude_command_options(
                    "prompt_only", "haiku", "low", input_format="stream-json"
                )
                code = await _run_control_probe(
                    [*argv, *options],
                    cwd,
                    probe.initial,
                    probe.handle,
                    stop,
                    deadline,
                )
            except (Failure, OSError) as failure:
                if isinstance(failure, Failure) and failure.error.code == "cancelled":
                    raise
            else:
                if code == 0:
                    limits = probe.limits
        return _Subscription(plan.casefold(), limits)
    except Failure as failure:
        if failure.error.code != "protocol_error":
            raise
        raise _unverified() from None
    except OSError:
        raise _unverified() from None
