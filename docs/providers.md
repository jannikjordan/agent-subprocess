# Provider compatibility

The adapters use the official binaries installed on the worker. The table
records live smoke tests through the Python API on macOS 27.2 on 2026-11-23.
Both CLIs used their existing signed-in accounts and synthetic inputs.

| Provider | CLI version | Model and effort requested | Verified profiles | Answer events |
| --- | --- | --- | --- | --- |
| Codex | `0.171.0` | `gpt-6-luna`, `low` | `prompt_only`, `workspace_read` | Completed snapshots |
| Claude Code | `2.1.330` | `haiku`, `low` | `prompt_only`, `workspace_read` | Text deltas and completed snapshots |

Both permission profiles require the exact CLI versions in the table.
The wrapper checks the version before sending the prompt so a CLI update
cannot silently change the permission flags. `workspace_read` is available
on macOS. The `prompt_only` process runner also targets Windows and Linux.
Use `Prompt.from_file(...)` on either OS to send the contents of a trusted
task file. Local inference was exercised on macOS. Separate fixture runs
check the OS-specific startup, pipes and process cleanup.

## Codex

- `exec` can read the prompt from stdin when the prompt argument is `-`.
  Select the model with `--model` and set reasoning effort with the
  `model_reasoning_effort` config override. Use the caller's selected
  directory as the child working directory. `--skip-git-repo-check` is
  available for authorized workspaces outside Git.
- `prompt_only` disables shell access and other host integrations. Codex
  runs without the user config. The wrapper refuses workspaces with project
  `.codex` configuration so it can avoid loading their hooks or tool servers.
- `workspace_read` enables Codex's bounded shell profile. Agent commands may
  read the approved workspace and Codex's `:minimal` runtime system paths.
  The native sandbox probe allowed the workspace read and denied writes, a
  read outside the workspace, a symlink escape and a loopback connection.
- `exec --json` emits structured work events and completed messages. To
  support live answer deltas or richer turn controls, evaluate Codex App
  Server over stdio as a separate transport behind the same adapter contract.

[Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
[Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
[Permission profiles](https://learn.chatgpt.com/docs/permissions)
[App Server](https://learn.chatgpt.com/docs/app-server)

## Claude Code

- Print mode supports text input and `--model` and `--effort`. Available
  effort levels depend on model and CLI version. The final `result` event
  carries the outcome. Inspect it alongside the process exit status.
- Claude starts in safe and restricted modes with MCP and approval prompts
  disabled. The adapter checks the capability report at session startup.
  `prompt_only` exposes no built-in tools. `workspace_read`
  selects `Read`, `Glob` and `Grep` within the working directory. The live
  fixture read returned only the approved workspace marker and a fixture
  project hook did not run. The live CLI reported `claude-haiku-5-5` for the
  `haiku` alias.
- Leave login with the official binary. For hosted use, check the intended
  authentication and deployment model against Anthropic's terms.

[Programmatic Claude Code](https://code.claude.com/docs/en/headless)
[CLI reference](https://code.claude.com/docs/en/cli-reference)
[Claude Code legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)

## Model, permissions and metadata

The wrapper forwards model and effort. `actual_model` is present when the
provider reports it. The tested Codex transport omitted it. Missing login,
exhausted usage and an unsupported model are separate outcomes when the
adapter can recognize them. Account and extra-usage settings stay with the
provider CLI and the account owner.

The child inherits a small set of process environment variables. Use a
dedicated trusted host with trusted system and administrator configuration.
Managed configuration can take precedence over CLI options. For separate
users or untrusted workloads, apply an independent OS or container boundary
and validate it before sharing the worker.

## Binary discovery

The default client searches absolute PATH entries first, then known
locations for native installers and package managers. It uses the first
compatible binary. Set an absolute `executables` override to select a specific
installation.

| OS | Known layouts |
| --- | --- |
| macOS | Native user installs, Apple Silicon and Intel Homebrew, standard npm prefixes, common binary directories, and known Codex desktop application bundles |
| Linux | Native user installs, Linuxbrew, standard npm prefixes and standard system and user binary locations |
| Windows | Native installer locations, WinGet links and recognized packages, and native payloads under standard npm prefixes |

`codex app-server` is a command on the full Codex CLI. The library uses it to
read account status and uses `codex exec` for inference. An installation
providing a standalone App Server component needs the full CLI for this API.

[Codex installation](https://learn.chatgpt.com/docs/cli)
[Claude Code installation](https://code.claude.com/docs/en/setup)

## Subscription sign-in

The library checks the selected CLI account before sending prompt text. Codex
uses a one-shot App Server `account/read` probe. Claude Code uses
`auth status --json`. The check reads the authenticated account and its
plan, and keeps returned identities and diagnostics out of results.

| Error | What the application should show |
| --- | --- |
| `auth_required` | Sign in through `codex login` or `claude auth login` on this worker. |
| `subscription_required` | Select an account with a supported subscription in the CLI. An API key or free account is insufficient. |
| `auth_check_failed` | The CLI returned an unreadable account status. Check the installed binary and try again. |

The check is a snapshot. Quota, workspace policy and concurrent sign-in
changes still affect what the provider accepts when a job starts.

[Codex account status](https://learn.chatgpt.com/docs/app-server#1-check-auth-state)
[Claude CLI authentication](https://code.claude.com/docs/en/cli-reference)

## List providers and usage

`await Client().list_providers()` returns one `ProviderInfo` per provider.
Each entry describes the detected executable, its version, whether the
version is compatible, sign-in status, and the plan when available.

```python
async def show_providers(client):
    for provider in await client.list_providers(include_usage=True):
        print(provider.provider, provider.version, provider.auth_status)
        for window in provider.limits:
            reset = window.resets_at.isoformat() if window.resets_at else None
            print(window.kind, window.used_percent, reset)
```

Usage is opt-in. `limits` contains reported session or weekly windows,
with usage as a percentage and a UTC reset time when supplied. A reported
zero is a real reading. Use `usage_status` to distinguish a skipped check
from unavailable quota data. A signed-in account can have unavailable limits.

Codex uses App Server's `account/rateLimits/read`. Claude uses a read-only
`get_usage` control request when supported. These checks can contact provider
status services. They start no inference session and expose no account email,
account ID or raw status response.

[Codex rate limits](https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt)
[Claude usage control](https://github.com/anthropics/claude-agent-sdk-typescript/blob/main/CHANGELOG.md#03169)

## Windows setup

Use the native `codex.exe` or `claude.exe` from the provider. If the CLI was
installed using a command shim, point the client at the native executable
with the `executables` setting. The process runner uses Win32 Job Objects
for cancellation and cleanup, and requires the default Python Proactor
event loop. Hosted or embedded applications using a Selector event loop
can run the library in a dedicated worker process.

[Codex release binaries](https://github.com/openai/codex/releases/tag/rust-v0.171.0)
[Claude Code setup on Windows](https://code.claude.com/docs/en/setup#setup-on-windows)
[Python subprocess support](https://docs.python.org/3/library/asyncio-subprocess.html)

The Corduno reference app has separate runtime evidence for older versions.
[Corduno provider evidence](https://github.com/getcorduno/documentation/blob/59f041cd0061105c63e58772fa54e1b0d82bbb71/evidence/providers.md)
