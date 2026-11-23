import asyncio
import math
import os
import re
import sys
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from ._auth import check_subscription
from ._discovery import executable_candidates
from ._models import (
    MAX_PROMPT_BYTES,
    AuthStatus,
    EventKind,
    Prompt,
    Provider,
    ProviderInfo,
    RunError,
    RunEvent,
)
from ._models import RunRequest, RunResult, RunStatus
from ._process import run_child
from ._providers import (
    CLI_VERSIONS,
    Decoder,
    Failure,
    command_options,
)
from ._providers import recognized_error

_BUFFERED_EVENTS = 128
_MAX_ANSWER_BYTES = 4_194_304
_Executable = str | Path | tuple[str | Path, ...]
_SEMVER = rb"[0-9]{1,9}(?:\.[0-9]{1,9}){2}(?:[-+][A-Za-z0-9][A-Za-z0-9.+-]{0,40})?"
_VERSION_OUTPUT = {
    "codex": re.compile(rb"codex-cli " + _SEMVER),
    "claude": re.compile(_SEMVER + rb" \(Claude Code\)"),
}


@dataclass(frozen=True, slots=True)
class _Installation:
    argv: tuple[str, ...]
    version: str | None

    def compatible(self, provider: Provider) -> bool:
        return self.version == CLI_VERSIONS[provider].decode("ascii")


def _validate_deadline(seconds: float) -> None:
    if (
        type(seconds) not in (int, float)
        or not 0 < seconds <= sys.float_info.max
        or not math.isfinite(seconds)
    ):
        raise Failure(
            "invalid_request",
            "The deadline must be a finite number of seconds above zero.",
        )


def _check_platform() -> None:
    if sys.platform not in ("darwin", "linux", "win32"):
        raise Failure(
            "unsupported_setting", "Provider processes require macOS, Windows or Linux."
        )


def _unsupported_version(provider: Provider) -> Failure:
    expected = CLI_VERSIONS[provider].decode("ascii")
    return Failure(
        "unsupported_setting", f"Use the verified provider CLI version: {expected}."
    )


async def _read_version(
    provider: Provider,
    argv: tuple[str, ...],
    cwd: Path,
    stop: asyncio.Future[None],
    deadline: float,
) -> str | None:
    version = None

    def check(record: bytes) -> None:
        nonlocal version
        line = record.strip()
        if version is not None or not _VERSION_OUTPUT[provider].fullmatch(line):
            raise _unsupported_version(provider)
        version = line.decode("ascii")

    try:
        code, _ = await run_child([*argv, "--version"], cwd, b"", check, stop, deadline)
    except Failure as failure:
        if failure.error.code != "unsupported_setting":
            raise
        return None
    return version if code == 0 else None


async def _find_installation(
    provider: Provider,
    executable: tuple[str, ...] | None,
    cwd: Path,
    stop: asyncio.Future[None],
    deadline: float,
) -> _Installation:
    if executable is not None:
        binary = Path(executable[0]).resolve(strict=True)
        if os.name == "nt" and binary.suffix.lower() != ".exe":
            raise Failure(
                "unsupported_setting",
                "Windows requires a native .exe provider launcher.",
            )
        argv = (str(binary), *executable[1:])
        return _Installation(
            argv, await _read_version(provider, argv, cwd, stop, deadline)
        )

    first_incompatible = None
    for binary in executable_candidates(provider, os.environ):
        argv = (str(binary),)
        try:
            installation = _Installation(
                argv, await _read_version(provider, argv, cwd, stop, deadline)
            )
        except OSError:
            continue
        if installation.compatible(provider):
            return installation
        if first_incompatible is None:
            first_incompatible = installation
    if first_incompatible is not None:
        return first_incompatible
    raise Failure("cli_missing", "Install the requested official provider CLI.")


def _os_error(error: OSError) -> RunError:
    if isinstance(error, FileNotFoundError):
        return RunError("cli_missing", "Install the requested official provider CLI.")
    if isinstance(error, PermissionError):
        return RunError("permission_denied", "The host denied access to the CLI.")
    return RunError("provider_error", "The host could not run the provider CLI.")


async def _provider_info(
    provider: Provider,
    executable: tuple[str, ...] | None,
    include_usage: bool,
    deadline: float,
) -> ProviderInfo:
    info = ProviderInfo(
        provider, usage_status="unavailable" if include_usage else "not_requested"
    )
    stop = asyncio.get_running_loop().create_future()
    try:
        _check_platform()
        with TemporaryDirectory(prefix="provider-cli-check-") as directory:
            cwd = Path(directory).resolve()
            installation = await _find_installation(
                provider, executable, cwd, stop, deadline
            )
            info = replace(
                info,
                executable=Path(installation.argv[0]),
                version=installation.version,
                compatible=installation.compatible(provider),
            )
            if not info.compatible:
                raise _unsupported_version(provider)
            account = await check_subscription(
                provider,
                installation.argv,
                cwd,
                stop,
                deadline,
                include_usage=include_usage,
            )
        return replace(
            info,
            auth_status="signed_in",
            plan=account.plan,
            limits=account.limits,
            usage_status="available" if account.limits else info.usage_status,
        )
    except Failure as failure:
        status: AuthStatus = "unknown"
        if failure.error.code == "auth_required":
            status = "signed_out"
        if failure.error.code == "subscription_required":
            status = "subscription_required"
        return replace(info, auth_status=status, error=failure.error)
    except OSError as error:
        return replace(info, error=_os_error(error))


class Session:
    """A live run handle with one event iterator and one shared result."""

    def __init__(self, request: RunRequest, executable: str | tuple[str, ...] | None):
        self.run_id = uuid.uuid4().hex
        self._request = request
        self._executable = (executable,) if isinstance(executable, str) else executable
        self._loop = asyncio.get_running_loop()
        self._stop: asyncio.Future[None] = self._loop.create_future()
        self._queue: asyncio.Queue[RunEvent] = asyncio.Queue(
            maxsize=_BUFFERED_EVENTS + 2
        )
        self._sequence = 0
        self._consumer = False
        self._overflow = False
        self._answer_bytes = 0
        self._task = self._loop.create_task(self._run(self._loop.time()))

    async def events(self) -> AsyncIterator[RunEvent]:
        """Read queued events, through the single terminal event."""
        if self._consumer:
            raise RuntimeError("A session supports one event iterator.")
        self._consumer = True
        while True:
            event = await self._queue.get()
            yield event
            if event.kind == "finished":
                return

    async def wait(self) -> RunResult:
        """Return the same result whether or not a stream is being consumed."""
        return await asyncio.shield(self._task)

    async def cancel(self) -> RunResult:
        """Request cancellation of an active run and wait for cleanup."""
        if not self._stop.done() and not self._task.done():
            self._stop.set_result(None)
        return await self.wait()

    def _emit(
        self,
        kind: EventKind,
        value: str | None = None,
        result: RunResult | None = None,
        *,
        required: bool = False,
    ) -> None:
        if not required and (self._overflow or self._queue.qsize() >= _BUFFERED_EVENTS):
            self._overflow = True
            return
        self._sequence += 1
        self._queue.put_nowait(
            RunEvent(
                run_id=self.run_id,
                provider=self._request.provider,
                sequence=self._sequence,
                kind=kind,
                text=value if kind in ("answer_delta", "answer_snapshot") else None,
                activity=value if kind == "activity" else None,
                result=result,
            )
        )

    def _record(self, decoder: Decoder, record: bytes) -> None:
        if (event := decoder.decode(record)) is None:
            return
        kind, value = event
        if kind in ("answer_snapshot", "answer_delta"):
            try:
                self._answer_bytes += len(value.encode("utf-8"))
            except UnicodeError:
                raise Failure(
                    "protocol_error", "The CLI sent invalid Unicode text."
                ) from None
            if self._answer_bytes > _MAX_ANSWER_BYTES:
                raise Failure(
                    "protocol_error", "The CLI exceeded the 4 MiB answer limit."
                )
        self._emit(kind, value)

    def _prepare(self) -> tuple[Path, bytes, float]:
        request = self._request
        seconds = request.deadline_seconds
        _validate_deadline(seconds)
        try:
            cwd = Path(request.cwd).resolve(strict=True)
            if not cwd.is_dir():
                raise ValueError
        except (OSError, RuntimeError, ValueError, TypeError):
            raise Failure(
                "invalid_request", "Choose an existing working directory."
            ) from None
        if not isinstance(request.prompt, Prompt) or not isinstance(
            request.prompt.content, str
        ):
            raise Failure(
                "invalid_request", "Supply a Prompt with text for the provider."
            )
        content = request.prompt.content
        if len(content) > MAX_PROMPT_BYTES:
            raise Failure("invalid_request", "The prompt exceeds the 1 MiB limit.")
        try:
            prompt = content.encode("utf-8")
        except UnicodeError:
            raise Failure(
                "invalid_request", "The prompt must be valid UTF-8."
            ) from None
        if len(prompt) > MAX_PROMPT_BYTES:
            raise Failure("invalid_request", "The prompt exceeds the 1 MiB limit.")
        if not content.strip() or "\0" in content:
            raise Failure(
                "invalid_request", "Supply a nonempty prompt without NUL characters."
            )
        return cwd, prompt, seconds

    def _outcome(
        self, decoder: Decoder, status: RunStatus, error: RunError | None
    ) -> RunResult:
        return RunResult(
            run_id=self.run_id,
            provider=self._request.provider,
            status=status,
            text=decoder.text if status == "succeeded" else None,
            error=error,
            native_session_id=decoder.native_session_id,
            actual_model=decoder.actual_model,
            usage=decoder.usage,
        )

    async def _execute(self, decoder: Decoder, started_at: float) -> None:
        _check_platform()
        cwd, content, seconds = self._prepare()
        options = command_options(self._request, cwd)
        deadline = started_at + seconds
        with TemporaryDirectory(prefix="provider-cli-check-") as directory:
            check_cwd = Path(directory).resolve()
            installation = await _find_installation(
                self._request.provider,
                self._executable,
                check_cwd,
                self._stop,
                deadline,
            )
            if not installation.compatible(self._request.provider):
                raise _unsupported_version(self._request.provider)
            argv = installation.argv
            await check_subscription(
                self._request.provider, argv, check_cwd, self._stop, deadline
            )
        returncode, stderr = await run_child(
            [*argv, *options],
            cwd,
            content,
            lambda record: self._record(decoder, record),
            self._stop,
            deadline,
            lambda: self._emit("started"),
        )
        if decoder.error is not None:
            error = decoder.error
            if error.code == "provider_error":
                error = recognized_error(stderr) or error
            raise Failure(error.code, error.message)
        if (
            returncode != 0
            or not decoder.terminal
            or not decoder.text
            or not decoder.text.strip()
        ):
            error = decoder.hint or recognized_error(stderr)
            if error is not None:
                raise Failure(error.code, error.message)
            if returncode != 0 and decoder.terminal:
                raise Failure(
                    "provider_error",
                    "The CLI exited unsuccessfully after its terminal event.",
                )
            raise Failure(
                "protocol_error", "The CLI exited without a usable terminal answer."
            )

    async def _run(self, started_at: float) -> RunResult:
        decoder = Decoder(self._request.provider, self._request.permissions)
        status: RunStatus = "succeeded"
        error = None
        try:
            await self._execute(decoder, started_at)
        except Failure as failure:
            error = failure.error
            status = (
                "timed_out"
                if error.code == "timeout"
                else ("cancelled" if error.code == "cancelled" else "failed")
            )
        except OSError as failure:
            status, error = "failed", _os_error(failure)
        result = self._outcome(decoder, status, error)
        if self._overflow:
            self._emit("activity", "stream_truncated", required=True)
        self._emit("finished", result=result, required=True)
        return result


class Client:
    """Launch local official provider CLIs with a shared session API."""

    def __init__(self, *, executables: Mapping[Provider, _Executable] | None = None):
        self._executables = {}
        for provider, executable in (executables or {}).items():
            argv = executable if isinstance(executable, tuple) else (executable,)
            if (
                provider not in ("codex", "claude")
                or not argv
                or any(
                    not isinstance(arg, (str, Path)) or "\0" in str(arg) for arg in argv
                )
                or not Path(argv[0]).is_absolute()
            ):
                raise ValueError(
                    "Use a trusted codex or claude command with an absolute executable path."
                )
            self._executables[provider] = tuple(map(str, argv))

    async def list_providers(
        self, *, include_usage: bool = False, deadline_seconds: float = 15
    ) -> tuple[ProviderInfo, ProviderInfo]:
        """Read installation and account snapshots for Codex and Claude without inference."""
        if type(include_usage) is not bool:
            raise ValueError("include_usage must be a boolean.")
        try:
            _validate_deadline(deadline_seconds)
        except Failure as failure:
            raise ValueError(failure.error.message) from None
        deadline = asyncio.get_running_loop().time() + deadline_seconds
        codex, claude = await asyncio.gather(
            _provider_info(
                "codex", self._executables.get("codex"), include_usage, deadline
            ),
            _provider_info(
                "claude", self._executables.get("claude"), include_usage, deadline
            ),
        )
        return codex, claude

    @asynccontextmanager
    async def start(self, request: RunRequest) -> AsyncIterator[Session]:
        """Start one run and clean it up when leaving the context."""
        session = Session(request, self._executables.get(request.provider))
        try:
            yield session
        finally:
            await session.cancel()

    async def run(self, request: RunRequest) -> RunResult:
        """Run a fresh session and wait for its terminal result."""
        async with self.start(request) as session:
            return await session.wait()
