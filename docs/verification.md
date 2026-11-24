# Verification

Install the package in an isolated environment using the
[README](../README.md), then run the library and example suites:

```sh
python -m unittest discover -s tests
python -m unittest discover -s examples/analysis_job
```

The [provider guide](providers.md) records the versions exercised in live
smoke tests. The checks below describe the evidence a release needs.

## Library checks

Use synthetic child processes and event fixtures so the normal test suite
runs without provider credentials or inference.

| Area | Acceptance check |
| --- | --- |
| Request | The correct binary receives the caller's model, effort, working directory and prompt. Cover inline content, a trusted prompt file and provider-side workspace reads. Unsupported settings stop before launch. |
| Process | Independently drain stdout and stderr. A result-only call and a slow or disconnected event consumer can complete or clean up according to the documented stream policy. |
| Events | Parse split reads and multiple records in a read. Preserve event order. Handle unknown events and explicitly fail on missing or malformed required terminal data. Assert one terminal outcome for success, failure, cancellation and timeout. |
| Lifecycle | Cover a missing executable, early exit, deadline and cancellation during startup and streaming. Verify cleanup of owned subprocesses within each supported platform's guarantees. |
| Permissions | Run in a disposable workspace with synthetic inherited hooks and MCP configuration. Verify denial of writes, reads outside the approved workspace, and agent-initiated network access. Use only fixture files and local test endpoints. Check that restricted profiles suppress inherited capabilities and refuse unsupported hosts or CLIs. |
| Structured data | When schemas ship, cover valid and invalid final output and malformed or unauthorized progress reports. Keep provider diagnostics out of answer and report payloads. |

Run opt-in smoke checks on macOS, Windows and Linux with the supported CLIs
and an authorized account. Use synthetic data and select `--model haiku`
explicitly for every live Claude Code test. Run the same small analysis
task with each provider, including a non-Git workspace, and verify the final
answer and the advertised events. Repeat permission and cancellation checks
on each supported combination. Record versions and results in the
compatibility guide. A fake process tests the wrapper. Actual CLI smoke
results establish runtime compatibility.

The Windows workflow runs the installed package and fixture suites without
provider credentials. It can run on a `dev` revision through manual dispatch,
or on the exact pull request head when the `run-windows-tests` label is
applied. The job uses a private GitHub-hosted runner allocation.

Pull requests targeting `main` automatically run the installed-package and
example suites on Linux, Windows and macOS. These jobs use fake executables
and synthetic account responses. Review the three `Release checks` results
before approving a release PR. Signed-in provider checks run on an
authorized local host.

Release automation tests use synthetic GitHub responses. After an approved
version bump reaches `main`, open the **Publish source release** run. Verify
the tag points to the merged commit and the notes match `CHANGELOG.md`.

## Consuming project checks

- Start with a fixture request through the application's normal entry
  point. On an authorized personal setup, opt in to a live check with
  synthetic data. Verify the model and workspace selection and confirm the
  result displays even when a provider offers no answer deltas.
- Exercise a missing runtime, rejected workspace and timeout. Confirm
  failures appear in the app's normal error path without exposing provider
  diagnostics.
- For background jobs, check cancellation, event ownership and duplicate
  delivery using the app's existing job and attempt IDs. Verify each retry
  creates a separate run and that the queue records the terminal state.
- For embedded chat, disconnect mid-run and check the cleanup or durable
  worker behavior selected by the app. Test rendering with synthetic HTML
  and confirm the app renders it according to its content policy.
- If structured results can trigger downstream work, submit a schema-valid
  but unauthorized result and verify the application refuses the action.
