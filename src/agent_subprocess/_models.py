from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

MAX_PROMPT_BYTES = 1_048_576

Provider = Literal["codex", "claude"]
AuthStatus = Literal["signed_in", "signed_out", "subscription_required", "unknown"]
UsageStatus = Literal["not_requested", "available", "unavailable"]
RateLimitKind = Literal["session", "weekly"]
Permission = Literal["prompt_only", "workspace_read"]
RunStatus = Literal["succeeded", "failed", "timed_out", "cancelled"]
EventKind = Literal[
    "started", "activity", "answer_delta", "answer_snapshot", "finished"
]


@dataclass(frozen=True, slots=True)
class Prompt:
    """A starting prompt to send as UTF-8 text on stdin."""

    content: str = field(repr=False)

    @classmethod
    def text(cls, content: str) -> "Prompt":
        """Use inline instructions as the starting prompt."""
        return cls(content)

    @classmethod
    def from_file(cls, path: str | Path) -> "Prompt":
        """Load a trusted UTF-8 prompt file with the application's access."""
        path = Path(path)
        if not path.is_file():
            raise ValueError("A prompt file must be a regular file.")
        with path.open("rb") as source:
            content = source.read(MAX_PROMPT_BYTES + 1)
        if len(content) > MAX_PROMPT_BYTES:
            raise ValueError("The prompt exceeds the 1 MiB limit.")
        return cls(content.decode("utf-8"))


@dataclass(frozen=True, slots=True)
class RunRequest:
    """Instructions and launch settings for one fresh provider session."""

    provider: Provider
    cwd: str | Path = field(repr=False)
    prompt: Prompt
    model: str | None = None
    effort: str | None = None
    permissions: Permission = "prompt_only"
    deadline_seconds: float = 120


@dataclass(frozen=True, slots=True)
class RunError:
    """A stable error code and a summary free of raw provider diagnostics."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class RateLimitWindow:
    """A provider-reported percentage and next reset for one quota window."""

    kind: RateLimitKind
    used_percent: float
    resets_at: datetime | None
    window_minutes: int


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """The installed CLI and a privacy-safe snapshot of its account status."""

    provider: Provider
    executable: Path | None = field(default=None, repr=False)
    version: str | None = None
    compatible: bool = False
    auth_status: AuthStatus = "unknown"
    plan: str | None = None
    limits: tuple[RateLimitWindow, ...] = ()
    usage_status: UsageStatus = "not_requested"
    error: RunError | None = None


@dataclass(frozen=True, slots=True)
class RunResult:
    """The authoritative terminal outcome of a run."""

    run_id: str
    provider: Provider
    status: RunStatus
    text: str | None = field(default=None, repr=False)
    error: RunError | None = None
    native_session_id: str | None = field(default=None, repr=False)
    actual_model: str | None = None
    usage: dict[str, int] | None = None


@dataclass(frozen=True, slots=True)
class RunEvent:
    """A normalized event from one run, ordered by its sequence number."""

    run_id: str
    provider: Provider
    sequence: int
    kind: EventKind
    text: str | None = field(default=None, repr=False)
    activity: str | None = None
    result: RunResult | None = None
