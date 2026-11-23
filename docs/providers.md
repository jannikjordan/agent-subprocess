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

## Windows setup

Use the native `codex.exe` or `claude.exe` from the provider. If the CLI was
installed using a command shim, point the client at the native executable
with the `executables` setting. The process runner uses Win32 Job Objects
for cancellation and cleanup, and requires the default Python Proactor
event loop. Hosted or embedded applications using a Selector event loop
can run the proxy in a dedicated worker process.

[Codex release binaries](https://github.com/openai/codex/releases/tag/rust-v0.171.0)
[Claude Code setup on Windows](https://code.claude.com/docs/en/setup#setup-on-windows)
[Python subprocess support](https://docs.python.org/3/library/asyncio-subprocess.html)

The Corduno reference app has separate runtime evidence for older versions.
[Corduno provider evidence](https://github.com/getcorduno/documentation/blob/59f041cd0061105c63e58772fa54e1b0d82bbb71/evidence/providers.md)
