# Ticket-count analysis job

The example reads [task.md](task.md), sends the synthetic ticket counts to
the proxy, and prints the final answer. The offline CLI fixtures let you
check the public API without credentials or provider traffic.

## Install and run

On macOS and Linux, run these commands from the repository root.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

Run either provider fixture in either mode.

```sh
python examples/analysis_job/analyze.py run --provider codex
python examples/analysis_job/analyze.py stream --provider claude
```

In Windows PowerShell, use the virtual environment's Python directly.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe examples/analysis_job/analyze.py run --provider codex
.\.venv\Scripts\python.exe examples/analysis_job/analyze.py stream --provider claude
```

Both commands print `18 tickets closed. Wednesday had the highest count
with 9.` on stdout. The `stream` command writes progress and available
answer updates to stderr, so other programs can still read the final answer
from stdout. The fixtures check that Python passes the contents of the
prompt file to the provider subprocess.

Run the smoke test to check both providers in both modes.

```sh
python -m unittest discover -s examples/analysis_job
```

## Use an installed provider

With the official CLI installed and signed in on a trusted host, add
`--live` to send the prompt to that provider under its existing account.
Use Haiku for live Claude smoke tests.

```sh
python examples/analysis_job/analyze.py stream --provider codex --live
python examples/analysis_job/analyze.py run --provider claude --live --model haiku --effort low
```

Use `--prompt-file` to send a different trusted file in live mode. Python
loads the file with the application's own permissions before invoking the
CLI under `prompt_only`. Use `--cwd` to set the process working directory.

To have the CLI open the file itself, add `--provider-read`. This requests
`workspace_read` and works only with a supported provider. Choose a prompt
file under `--cwd`. A relative `--prompt-file` in this mode is resolved from
that working directory.

```sh
python examples/analysis_job/analyze.py stream --provider claude --live --provider-read --model haiku --effort low
```

See the [session contract](../../docs/session-contract.md) and
[provider guide](../../docs/providers.md) for permission coverage.
