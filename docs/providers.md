# Provider compatibility

The adapters use the official binaries installed on the worker. On
2026-11-23, local `--version` and `--help` checks identified these starting
versions. The library has no verified runtime or permission profiles yet.

| Provider | Observed CLI version | Initial transport | Stream granularity |
| --- | --- | --- | --- |
| Codex | `0.171.0` | `codex exec --json` | JSONL lifecycle, activity and completed assistant messages |
| Claude Code | `2.1.330` | `claude --print --output-format stream-json --verbose` | JSONL messages and results. `--include-partial-messages` asks for text deltas when used with stream JSON. |

## Codex

- `exec` can read the prompt from stdin when the prompt argument is `-`.
  Select the model with `--model` and set reasoning effort with the
  `model_reasoning_effort` config override. Use the caller's selected
  directory as the child working directory. `--skip-git-repo-check` is
  available for authorized workspaces outside Git.
- Sandbox and approval policy are separate settings. To verify a permission
  profile, check what can run through hooks, tool servers and other host
  tools in addition to checking whether file writes are blocked.
- `exec --json` emits structured work events and completed messages. To
  support live answer deltas or richer turn controls, evaluate Codex App
  Server over stdio as a separate transport behind the same adapter contract.

[Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
[Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
[App Server](https://learn.chatgpt.com/docs/app-server)

## Claude Code

- Print mode supports text input and `--model` and `--effort`. Available
  effort levels depend on model and CLI version. The final `result` event
  carries the outcome. Inspect it alongside the process exit status.
- Verify effective restrictions for every supported profile. Permission
  modes govern tool decisions. Tool selection, safe mode, strict MCP config
  and `--permission-prompts none` affect different parts of the boundary.
  Normal print mode can load workspace customizations, so confirm the
  effective behavior before advertising a restricted profile.
- Leave login with the official binary. For hosted use, check the intended
  authentication and deployment model against Anthropic's terms.

[Programmatic Claude Code](https://code.claude.com/docs/en/headless)
[CLI reference](https://code.claude.com/docs/en/cli-reference)
[Claude Code legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)

## Model, permissions and metadata

Accept the caller's requested provider, model and effort. Validate supported
settings where the runtime reports them reliably. Expose the actual model
  only when the provider reports it. Missing login, exhausted usage and an
unsupported model are separate outcomes whenever the adapter can tell them
apart. Keep provider selection and billing mode fixed for a run.

Restrict the environment and configuration passed to the child to the job's
approved setup. An allowed working directory is a starting location. Use
verified provider restrictions and host isolation for access boundaries.
Before advertising a permission profile, record the effective tools, file
access, network access, and inherited settings checked on the target OS.

For each tested release, record OS and CLI version, model and effort,
authentication mode without account identifiers, permission profile, event
kinds, cancellation behavior, and resume if supported. Mark each capability
as help-confirmed, runtime-verified or unverified. The Corduno reference app
has its own runtime evidence for older versions. [Corduno provider evidence](https://github.com/getcorduno/documentation/blob/59f041cd0061105c63e58772fa54e1b0d82bbb71/evidence/providers.md)
