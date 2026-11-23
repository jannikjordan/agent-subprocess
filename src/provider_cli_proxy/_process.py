import asyncio
import os
import signal
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import TypeVar

from ._providers import Failure, child_environment

_T = TypeVar("_T")
_MAX_RECORD = 1_048_576
_STDERR_SAMPLE = 65_536
_GRACE = 0.25


class _ProcessProtocol(asyncio.subprocess.SubprocessStreamProtocol):
    def __init__(self) -> None:
        loop = asyncio.get_running_loop()
        super().__init__(limit=_MAX_RECORD, loop=loop)
        self.exited: asyncio.Future[int] = loop.create_future()

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


def _signal_group(transport: asyncio.SubprocessTransport, signum: int) -> bool:
    try:
        os.killpg(transport.get_pid(), signum)
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
            if not await _finish_pipes(protocol.process, pipes):
                raise Failure(
                    "protocol_error", "The CLI left an output stream open after exit."
                )
        await pipes
        return await protocol.exited, tasks[2].result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(pipes, *tasks, return_exceptions=True)


async def _finish_pipes(
    transport: asyncio.SubprocessTransport, pipes: asyncio.Future
) -> bool:
    for signum in (signal.SIGTERM, signal.SIGKILL):
        _signal_group(transport, signum)
        done, _ = await asyncio.wait((pipes,), timeout=_GRACE)
        if done:
            return True
    return False


async def _cleanup(protocol: _ProcessProtocol, worker: asyncio.Task | None) -> None:
    try:
        if _signal_group(protocol.process, signal.SIGTERM):
            await asyncio.sleep(_GRACE)
            _signal_group(protocol.process, signal.SIGKILL)
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
    """Run one process in a new session and clean up its pipes and group."""
    if stop.done():
        raise Failure("cancelled", "The run was cancelled.")
    loop = asyncio.get_running_loop()
    if loop.time() >= deadline:
        raise Failure("timeout", "The run exceeded its deadline.")
    spawn = asyncio.create_task(
        loop.subprocess_exec(
            _ProcessProtocol,
            *command,
            cwd=cwd,
            env=child_environment(),
            start_new_session=True,
        )
    )
    protocol = None
    worker = None
    try:
        _, protocol = await _before_stop(spawn, stop, deadline)
        if stop.done():
            raise Failure("cancelled", "The run was cancelled.")
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
