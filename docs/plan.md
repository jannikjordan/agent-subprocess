# Build and release plan

## First usable release

An existing Python project can install the package, submit a prompt to
Codex or Claude Code, and wait for the result or consume live events. Ship a
separate example app that uses only the public API. Start on Python 3.11+
with macOS and Linux as the initial verification targets.

## Phases

| Phase | Deliverables and exit criteria |
| --- | --- |
| 1. Headless runner | Package `provider_cli_proxy`. Typed requests, results and events. Run both CLIs without a shell using caller-selected provider, model, effort, cwd and permission profile. Cover inline prompts, Python-loaded prompt files and provider-side file reads where enforced. Waiting and streaming share a run. Test cancellation, timeouts, pipe draining, overflow and cleanup. |
| 2. Adoption | Install the package in a clean environment and run `examples/analysis_job` with fake CLIs and synthetic data. Run one-shot and streaming flows. Use short prompts for live smoke tests and select Haiku for Claude Code. Record actual results. Document installation, API behavior and permission coverage. |
| 3. Assistant extensions | Verify explicit native resume, validated final schemas, live milestone reports and Codex text deltas behind capabilities. Each extension needs separate fixtures and a real-runtime check before it is advertised. |
| 4. Tool extensions | Publish integration examples for authorized tools after verifying the host's permission boundary. The consuming app supplies tool policy and manages its own queue, accounts, network and machines. |

Phases 1 and 2 are the first delivery. Work in branches off `dev` and
integrate tested changes after independent Codex review. Promote to `main`
after release checks pass and the owner approves the release.

## Implementation

- Put the public types and `Client` in `src/provider_cli_proxy`. Keep process
  management separate from provider-specific argument construction and event
  decoding. Use `asyncio` and a fresh POSIX process group per run. Set a
  deadline for the run, drain both pipes concurrently and reap the group on
  cancel or timeout. Scope the guarantee to managed process groups.
- Send prompts over stdin. Build argv from explicit validated fields, and
  use documented CLI options instead of arbitrary extra flags. For auth,
  reuse the installed binary's existing login. Pass a narrow environment
  with telemetry disabled and avoid implicit credentials or paid fallbacks.
  Capture safe error codes and summaries. Suppress raw diagnostics and
  provider payloads from application-facing status.
- Check exact CLI versions before sending a prompt. For `prompt_only`,
  disable host execution and workspace customization in the supported CLI
  configuration. Treat the installed binary, OS user and administrative
  configuration as trusted. Test ordinary inherited hooks
  and tool server config using a disposable workspace. For `workspace_read`,
  advertise a provider only after proving workspace confinement, denied
  writes and denied agent network access. Refuse profiles that cannot be
  enforced before starting inference. Python can load trusted instructions
  and task data for `prompt_only` independently of provider tool support.
- Bound prompt, pipe records and buffered events. Missing required provider
  completion data fails unless a recognizable provider error explains the
  outcome. Unknown optional events can be ignored. Cancel and timeout
  settle once and emit one terminal result. Keep these behaviors under
  credential-free tests with fixture processes.
- Use the Python standard library at runtime. Build the wheel with
  `setuptools==84.2.1`, the latest stable version verified on 2026-11-23.
  Its PyPI record supports Python 3.10+ and OSV returned no advisories for
  that version. [Setuptools on PyPI](https://pypi.org/project/setuptools/84.2.1/)

## Release evidence

Test a clean install, an example that imports the installed wheel, both
provider event formats, the OS-specific process behavior and the permission
claims shown in the README. A live CLI flag becomes runtime-verified only
after a matching smoke test. Keep failures and unverified combinations
visible in the [compatibility guide](providers.md).

## macOS, Windows and Linux

Deliver the same `prompt_only` API on all three systems. It covers literal
and Python-loaded file prompts, model and effort selection, streaming,
timeouts and cancellation. The caller can submit a task file on every OS.
Native `workspace_read` stays enabled only where the provider's effective
filesystem, write and network restrictions have been verified.

- Keep POSIX process-group cleanup. On Windows, start a small trusted Python
  bootstrap, attach it to a kill-on-close Win32 Job Object and only then
  signal it to launch the provider. The job owns the provider and descendants
  during deadlines, cancellation and parent exit. Keep prompt bytes on
  stdin and require the default Proactor event loop on Windows.
- Resolve native Windows executables from trusted absolute paths or PATH
  entries. Batch and command shims would invoke a shell. Accept a trusted
  executable prefix for portable Python fixtures and explicit launchers.
  Forward the minimum Windows runtime paths alongside the existing environment
  allowlist. Treat Job Objects as process cleanup, with provider controls
  responsible for workspace and tool permissions.
- Convert fixture launchers and lifecycle assertions to run on POSIX and
  Windows. Test installation and both provider fixtures on each OS. Check
  process-tree cleanup when the provider exits while a descendant keeps a
  pipe open. Keep live tests opt-in and use Haiku for all Claude inference.
- Record offline and native evidence separately. Use a disposable Windows
  runner for fixture tests. Native provider checks require the official CLI
  and the user's existing authorization on that host.

[Win32 Job Objects](https://learn.microsoft.com/windows/win32/procthread/job-objects)
[Python subprocess support](https://docs.python.org/3/library/asyncio-subprocess.html)
