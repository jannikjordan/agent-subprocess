# Ticket-count analysis job

Start with [minimal.py](minimal.py). It reads synthetic ticket counts from
[task.md](task.md), runs a fake Codex CLI and prints the answer. The whole
example runs without a provider account or inference.

## Start with one file

After installing the library, run this from the repository root.

```sh
python examples/analysis_job/minimal.py
```

The result appears on stdout.

```text
18 tickets closed. Wednesday had the highest count with 9.
```

In the script, `Prompt.from_file()` loads the task and `Client.run()` waits
for the answer. The `executables` argument points the client to the
[fixture](fake_provider.py). For a live personal script, use `Client()`
with an installed, signed-in CLI and update the provider in your request.
See [personal use](../../README.md#personal-use).

## Try another provider or stream updates

If you need an isolated environment, set it up from the repository root.
Use these commands on macOS or Linux.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

The [full runner](analyze.py) can wait for the answer or print updates as
they arrive.

```sh
python examples/analysis_job/analyze.py run --provider codex
python examples/analysis_job/analyze.py stream --provider claude
```

In Windows PowerShell, use the virtual environment's Python directly.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe examples/analysis_job/minimal.py
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
