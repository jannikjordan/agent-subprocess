from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from ._providers import Failure, child_environment

if TYPE_CHECKING:
    from ._windows import WindowsJob

_T = TypeVar("_T")
_MAX_RECORD = 1_048_576
_STDERR_SAMPLE = 65_536
_GRACE = 0.25


class _ProcessProtocol(asyncio.subprocess.SubprocessStreamProtocol):
    def __init__(self) -> None:
        loop = asyncio.get_running_loop()
        super().__init__(limit=_MAX_RECORD, loop=loop)
        self.exited: asyncio.Future[int] = loop.create_future()
        self.job: WindowsJob | None = None

    def connection_made(self, transport: asyncio.SubprocessTransport) -> None:
        super().connection_made(transport)
        self.process = transport

    def process_exited(self) -> None:
        super().process_exited()
        code = self.process.get_returncode()
        assert code is not None
        self.exited.set_result(code)


async def _before_stop(
    task: asyncio.Task[_T], stop: asyncio.Future[None], deadline: float
) -> _T:
    remaining = max(0, deadline - asyncio.get_running_loop().time())
    done, _ = await asyncio.wait(
        (task, stop), timeout=remaining, return_when=asyncio.FIRST_COMPLETED
    )
    if task in done:
        return task.result()
    if stop in done:
        raise Failure("cancelled", "The run was cancelled.")
    raise Failure("timeout", "The run exceeded its deadline.")


def _stop_tree(protocol: _ProcessProtocol, *, force: bool = False) -> bool:
    if os.name == "nt":
        if protocol.job is not None:
            protocol.job.close()
        elif not protocol.exited.done():
            # An unassigned bootstrap never received permission to launch.
            with suppress(ProcessLookupError):
                protocol.process.kill()
        return False
    try:
        os.killpg(
            protocol.process.get_pid(), signal.SIGKILL if force else signal.SIGTERM
        )
    except ProcessLookupError:
        return False
    return True


async def _write_prompt(stream: asyncio.StreamWriter, prompt: bytes) -> None:
    try:
        stream.write(prompt)
        await stream.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass  # A startup failure may close stdin before reporting its cause.
    finally:
        stream.close()


async def _read_stdout(
    stream: asyncio.StreamReader, on_record: Callable[[bytes], None]
) -> None:
    try:
        while record := await stream.readline():
            if len(record) > _MAX_RECORD:
                raise Failure(
                    "protocol_error", "The CLI sent a record larger than 1 MiB."
                )
            if record.strip():
                on_record(record)
    except ValueError:
        raise Failure(
            "protocol_error", "The CLI sent a record larger than 1 MiB."
        ) from None


async def _read_stderr(stream: asyncio.StreamReader) -> str:
    sample = bytearray()
    while chunk := await stream.read(16_384):
        sample.extend(chunk[: max(0, _STDERR_SAMPLE - len(sample))])
    return sample.decode("utf-8", errors="replace")


async def _interact(
    protocol: _ProcessProtocol, prompt: bytes, on_record: Callable[[bytes], None]
) -> tuple[int, str]:
    assert (
        protocol.stdin is not None
        and protocol.stdout is not None
        and protocol.stderr is not None
    )
    tasks = (
        asyncio.create_task(_write_prompt(protocol.stdin, prompt)),
        asyncio.create_task(_read_stdout(protocol.stdout, on_record)),
        asyncio.create_task(_read_stderr(protocol.stderr)),
    )
    pipes = asyncio.gather(*tasks)
    try:
        done, _ = await asyncio.wait(
            (pipes, protocol.exited), return_when=asyncio.FIRST_COMPLETED
        )
        if pipes not in done:
            # A child can hold a stream open after the CLI process exits.
            if not await _finish_pipes(protocol, pipes):
                raise Failure(
                    "protocol_error", "The CLI left an output stream open after exit."
                )
        await pipes
        return await asyncio.shield(protocol.exited), tasks[2].result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(pipes, *tasks, return_exceptions=True)


async def _finish_pipes(protocol: _ProcessProtocol, pipes: asyncio.Future) -> bool:
    for force in (False, True):
        _stop_tree(protocol, force=force)
        done, _ = await asyncio.wait((pipes,), timeout=_GRACE)
        if done:
            return True
    return False


async def _cleanup(protocol: _ProcessProtocol, worker: asyncio.Task | None) -> None:
    try:
        if _stop_tree(protocol):
            await asyncio.sleep(_GRACE)
            _stop_tree(protocol, force=True)
        await asyncio.wait((protocol.exited,), timeout=_GRACE)
    finally:
        protocol.process.close()
        if worker is not None:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        await asyncio.wait((protocol.exited,), timeout=_GRACE)


async def run_child(
    command: list[str],
    cwd: Path,
    prompt: bytes,
    on_record: Callable[[bytes], None],
    stop: asyncio.Future[None],
    deadline: float,
    on_started: Callable[[], None] | None = None,
) -> tuple[int, str]:
    """Run one process in a managed tree and clean up its pipes and descendants."""
    if stop.done():
        raise Failure("cancelled", "The run was cancelled.")
    loop = asyncio.get_running_loop()
    if loop.time() >= deadline:
        raise Failure("timeout", "The run exceeded its deadline.")
    spawn_options = {"start_new_session": True}
    if os.name == "nt":
        if not isinstance(loop, asyncio.ProactorEventLoop):
            raise Failure(
                "unsupported_setting", "Windows requires a Proactor event loop."
            )
        if not Path(sys.executable).is_absolute():
            raise Failure(
                "unsupported_setting", "Windows requires an absolute Python executable."
            )
        from ._windows import WindowsJob, bootstrap_args

        command, creationflags = bootstrap_args(command)
        spawn_options = {"creationflags": creationflags}
    spawn = asyncio.create_task(
        loop.subprocess_exec(
            _ProcessProtocol,
            *command,
            cwd=cwd,
            env=child_environment(),
            **spawn_options,
        )
    )
    protocol = None
    worker = None
    try:
        _, protocol = await _before_stop(spawn, stop, deadline)
        if stop.done():
            raise Failure("cancelled", "The run was cancelled.")
        if os.name == "nt":
            try:
                protocol.job = WindowsJob(protocol.process.get_pid())
            except OSError:
                raise Failure(
                    "provider_error", "Windows could not contain the provider process."
                ) from None
            if loop.time() >= deadline:
                raise Failure("timeout", "The run exceeded its deadline.")
            prompt = b"\x01" + prompt
        if on_started is not None:
            on_started()
        worker = asyncio.create_task(_interact(protocol, prompt, on_record))
        return await _before_stop(worker, stop, deadline)
    finally:
        if protocol is None:
            # A timeout can race the OS creating the process. Keep a handle so it can be reaped.
            with suppress(OSError):
                _, protocol = await asyncio.shield(spawn)
        if protocol is not None:
            await _cleanup(protocol, worker)
