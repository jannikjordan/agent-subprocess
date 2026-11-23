# Provider CLI Proxy

Run Codex and Claude Code from Python. Send a prompt to an installed CLI,
wait for the final answer or stream activity and answer updates into an
existing application.

Use it for a one-off analysis script, a worker that handles jobs from your
queue, or the provider layer behind an embedded assistant. Your application
chooses the task, owns the queue and permissions, and decides how to display
or use the answer.

## Try it without a provider account

Use Python 3.11 or newer on macOS, Windows or Linux. On macOS or Linux,
run these commands from the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
python examples/analysis_job/analyze.py run --provider codex
python examples/analysis_job/analyze.py stream --provider claude
```

On Windows, use PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe examples/analysis_job/analyze.py run --provider codex
.\.venv\Scripts\python.exe examples/analysis_job/analyze.py stream --provider claude
```

The example uses fake executables by default and reads a synthetic analysis
prompt from a file. The streaming command sends progress to stderr and the
final answer to stdout. To use an installed, signed-in CLI, add `--live` and
optionally set `--model` and `--effort` for your account. Real runs use your
provider's configured account and quota. On a supported version, add
`--provider-read` to ask the CLI to open the instruction file itself.
Building the package can fetch setuptools from PyPI. The installed package
has no Python runtime dependencies.

## Call it from your application

In another project, install from a checkout with `python -m pip install
/path/to/provider-cli-proxy`, or use your existing GitHub access to install
from a reviewed commit. Replace `COMMIT_SHA` with the approved revision for
your deployment.

```sh
python -m pip install "git+https://github.com/jannikjordan/provider-cli-proxy.git@COMMIT_SHA"
```

Run this from a trusted workspace with the provider CLI installed and signed in.
On Windows, use the native provider `.exe` and Python's default Proactor
event loop.

```python
import asyncio
from pathlib import Path

from provider_cli_proxy import Client, Prompt, RunRequest


async def main() -> None:
    result = await Client().run(
        RunRequest(
            provider="codex",
            cwd=Path.cwd(),
            prompt=Prompt.text("Explain in one sentence what a job queue does."),
            permissions="prompt_only",
            deadline_seconds=60,
        )
    )
    if result.status == "succeeded":
        print(result.text)
    else:
        raise SystemExit(result.error.code if result.error else result.status)


if __name__ == "__main__":
    asyncio.run(main())
```

Set `model` and `effort` to select values supported by the chosen CLI. Use
`Prompt.from_file(Path("task.md"))` to load a trusted UTF-8 instruction file
into the initial prompt. The application reads that file under its own OS
permissions. This works on Windows, macOS and Linux. On a verified
`workspace_read` combination, you can also ask the provider to open task
files relative to the selected workspace.

For live updates, use `async with client.start(request) as session` and
iterate `session.events()`. The same session exposes `wait()` and `cancel()`.
Forward events through your application's existing transport. Codex `exec`
emits completed answer snapshots. Claude Code can also emit text deltas.
Use the final result to reconcile the displayed answer and finish the job.

## Provider boundaries

Use a trusted worker host and approved workspaces. `prompt_only` is for
prompts supplied as text. Install an exact CLI version from the compatibility
guide. It also lists where an adapter can offer `workspace_read` and which
restrictions were verified. Unsupported profiles and CLI versions fail before
inference. Keep authentication with the
official CLI and use an OS or container boundary where your application
requires isolation between users. Local CLIs send prompts to their configured
providers.

## Docs

- [Integration guide](docs/integration.md) for analysis, streaming and jobs.
- [Python session contract](docs/session-contract.md) for types and failures.
- [Provider compatibility](docs/providers.md) for supported combinations.
- [Verification](docs/verification.md) for the test and smoke-test workflow.
- [Build plan](docs/plan.md) for delivery phases and the release gate.
