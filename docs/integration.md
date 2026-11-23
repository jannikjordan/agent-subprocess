# Integrate with an existing Python project

The examples use the [proposed API](session-contract.md). They illustrate
where the proxy fits in code that already has application settings and a
worker or request handler. Package installation and runtime execution are
pending implementation.

## Set up the worker

1. Use a supported host with the official provider CLI installed and
   authorized for the intended workload. Check the [compatibility record](providers.md)
   for that binary version, OS and permission profile.
2. Resolve the provider, model, effort, deadline and workspace from trusted
   application settings. If the app lets users select a model or provider,
   validate the selection against the app's allowlist. Resolve workspace
   paths against a root authorized for that user or job.
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

from provider_cli_proxy import Client, Prompt, RunRequest, RunResult


async def analyze(
    client: Client,
    *,
    provider: str,
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

The app turns the shared events into its existing stream format. For an
embedded chat, build the request from authorized page context and the user's
message. The browser app owns display and safe Markdown rendering.

```python
from collections.abc import AsyncIterator

from provider_cli_proxy import Client, RunEvent, RunRequest


async def assistant_events(
    client: Client, request: RunRequest
) -> AsyncIterator[RunEvent]:
    async with client.start(request) as session:
        async for event in session.events():
            yield event
```

Append `answer_delta` and replace the current answer on `answer_snapshot`.
On `finished`, use the terminal result as the authoritative final answer and
status. Feed `activity` and `report` into the progress UI. Some providers or
runs produce no progress between start and completion. On disconnect, close
the iterator so a request-scoped session can cancel and clean up. For work
that should outlive the connection, run it in the app's worker and subscribe
to the app's job events from the browser.

## Run from an existing job queue

- Let the queue own the durable job ID and the worker own each live proxy
  session. Map the job ID and attempt ID to the proxy run ID. Record a native
  session ID only when your app needs explicit resume.
- Publish events under the app's job access rules and store the result after
  checking its terminal status. For a machine-readable handoff, request
  schema-validated output when the feature is available. Validate business
  rules in the app before taking an action.
- Route user cancellation to the worker that owns the live session.
  Base retry decisions on the error and any side effects of the previous
  attempt. On worker loss, use the queue's reconciliation and retry policy.
  A native provider session ID identifies conversation history. The queue
  supplies the state needed to recover a job.

Use the app's transcript retention and access rules. Keep raw tool output and
provider diagnostics out of browser responses. See the [integration checks](verification.md#consuming-project-checks)
before enabling a caller-facing entry point.
