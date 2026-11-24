# Integrate with an existing Python project

Run the [offline example](../examples/analysis_job/README.md) to see a
complete request before connecting your own script, local web app or job
worker. These examples use the [public Python API](session-contract.md).
Follow the [personal-use scope](../README.md#personal-use) for
subscription-backed runs.

## Set up the worker

1. Use a supported host with the official provider CLI installed and
   authorized for the intended workload. Check the [compatibility record](providers.md)
   for that binary version, OS and permission profile. On Windows, install
   the native executable and run with Python's default Proactor event loop.
2. Resolve the provider, model, effort, deadline and workspace from trusted
   application settings. Validate model and provider choices against the
   app's allowlist. Resolve workspace paths against the configured root for
   the job.
3. Choose the prompt source in the application. Use `Prompt.text(...)` for
   inline instructions. Use `Prompt.from_file(...)` to load a trusted file
   in Python and send its contents as the starting prompt. Use a text prompt
   such as `Read task.md and follow its instructions.` with `workspace_read`
   when the CLI itself should open a file relative to its working directory.
   Python-side file loading uses the application's own permissions.

## Wait for a one-shot result

This example loads instructions from a trusted file chosen by the application.
The settings values come from the consuming project.

```python
from pathlib import Path

from agent_subprocess import Client, Prompt, Provider, RunRequest, RunResult


async def analyze(
    client: Client,
    *,
    provider: Provider,
    model: str,
    effort: str,
    workspace: Path,
    trusted_prompt_file: Path,
) -> RunResult:
    return await client.run(
        RunRequest(
            provider=provider,
            model=model,
            effort=effort,
            cwd=workspace,
            permissions="prompt_only",
            prompt=Prompt.from_file(trusted_prompt_file),
            deadline_seconds=120,
        )
    )
```

Check `result.status` before using `result.text`. Translate a failed result
with `result.error.code` through the application's existing error handling.
If the analysis also needs workspace files, grant the verified read profile
and pass their paths in the instructions. A standalone script can call the
coroutine with `asyncio.run(...)` at its entry point. Inside an async worker
or web server, await it on the existing event loop.

## Stream an assistant response

Connect a personal assistant to the app's existing stream. Build the
request from your message and page context you can send to the provider.
The browser app handles display and safe Markdown rendering.

```python
from collections.abc import AsyncIterator

from agent_subprocess import Client, RunEvent, RunRequest


async def assistant_events(
    client: Client, request: RunRequest
) -> AsyncIterator[RunEvent]:
    async with client.start(request) as session:
        async for event in session.events():
            yield event
```

Append `answer_delta` and replace the current answer on `answer_snapshot`.
On `finished`, use the terminal result as the authoritative final answer and
status. Feed `activity` into the progress UI. Some providers or
runs produce no progress between start and completion. On disconnect, close
the iterator so a request-scoped session can cancel and clean up. For work
that should outlive the connection, run it in the app's worker and subscribe
to the app's job events from the browser.

## Run from an existing job queue

- Let the queue own the durable job ID and the worker own each live
  session. Map the job and attempt IDs to the library's run ID. Native IDs
  are optional diagnostic metadata.
- Deliver events through the app's job stream and store the result after
  checking its terminal status. For a machine-readable handoff, parse and
  validate the answer in the app before taking an action.
- Route cancellation to the worker that owns the live session.
  Base retry decisions on the error and any side effects of the previous
  attempt. On worker loss, use the queue's reconciliation and retry policy.
  A native provider session ID identifies conversation history. The queue
  supplies the state needed to recover a job.

Use the app's transcript retention and access rules. Keep raw tool output and
provider diagnostics out of browser responses. See the [integration checks](verification.md#consuming-project-checks)
before enabling a live entry point.
