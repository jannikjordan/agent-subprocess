# Python session contract

Import the public types from `provider_cli_proxy`. See the
[compatibility record](providers.md) for supported runtime features.

## Request

| Field | Meaning |
| --- | --- |
| `provider` | `codex` or `claude` |
| `model`, `effort` | Provider-specific values. Omission delegates the choice to that provider. The wrapper forwards explicit values and surfaces provider errors. Compare the reported actual model when the provider resolves an alias. |
| `cwd` | An existing host directory selected by the caller. Relative paths inside the task resolve from this workspace. |
| `permissions` | `prompt_only` is the default and disables host tools. `workspace_read` permits read-only task access within the approved workspace on the verified combinations. Consult the provider guide for runtime filesystem exceptions. An unsupported profile fails before inference. |
| `prompt` | One starting prompt, up to 1 MiB encoded as UTF-8. `Prompt.text(...)` carries text. `Prompt.from_file(...)` loads a regular UTF-8 file using the application's access before starting a provider process. |
| `deadline_seconds` | Positive time limit for the run, including startup. Terminal completion follows cleanup. |

Pass an instruction like `Read task.md and follow its instructions.` as text
when the provider should open the file itself. The application approves the
workspace and the requested permission profile independently of prompt text.

## Run and cancellation

- `Client()` resolves the official CLI using PATH and the known locations in
  the [provider guide](providers.md#binary-discovery). The optional
  `executables` mapping selects a trusted absolute path or a tuple with the
  absolute executable path followed by fixed launcher arguments. Choose
  executables in deployment configuration. Windows uses native `.exe`
  launchers and the default Proactor event loop. Each run checks the
  exact supported CLI version and subscription sign-in before sending the
  prompt. Use
  `await client.run(request)` to get a `RunResult` without a streaming consumer.
- `async with client.start(request) as session` starts a run. Use
  `session.events()` for one async event iterator, `await session.wait()` for
  the result and `await session.cancel()` to request cancellation. Events
  and `wait()` refer to the same run. Leaving the context requests cleanup
  of a still-active run. Expected startup failures yield a session with a
  failed result and a `finished` event.
- Use an application-owned run ID to route events and cancellation. The
  proxy supplies its own run ID for correlation. The native session ID has
  meaning only to its provider.
- The process runner continually drains stdout and stderr. A client waiting
  without reading events can still finish. If the queue fills at 128 pending
  events, the remaining live updates are dropped and `stream_truncated`
  precedes `finished`. The final result remains authoritative. The runner
  caps native records at 1 MiB and total emitted answer text at 4 MiB.
  Cancellation and deadline handling stop the managed process group on POSIX
  or the Win32 Job Object on Windows, then resolve the same terminal outcome
  for both readers.

## Provider inventory

Use `await client.list_providers(include_usage=False, deadline_seconds=15)` to
inspect availability without a prompt. The result contains `ProviderInfo`
entries for both providers, including missing or incompatible CLIs. Inspect
`auth_status` and `error` to decide what the user should do next. Ask for
usage explicitly to get `RateLimitWindow` entries where reported. See
[provider inventory](providers.md#list-providers-and-usage).

## Events and results

Each event has a run ID, a provider, a kind and a per-run sequence number.
Sequence gives the order observed by the proxy. The event stream ends with
one `finished` event carrying a `RunResult`, including when startup fails.

| Event | Meaning |
| --- | --- |
| `started` | The managed launch is active. Native session metadata can arrive later. |
| `activity` | Available user-visible work status from the runtime, such as a tool starting or completing. |
| `answer_delta` | Append this text to the current response. Produced by a transport that exposes text deltas. |
| `answer_snapshot` | Replace the current response with this complete text. Used for completed messages or to reconcile the displayed answer. |
| `finished` | Terminal result. The successful final text in the result is authoritative. |

`RunResult` includes the run ID, provider and a `status` of `succeeded`,
`failed`, `timed_out` or `cancelled`. A successful result carries `text`.
Provider metadata such as `native_session_id`,
`actual_model` and `usage` is optional. Requested values remain distinguishable
from values observed in provider output. Partial text can be displayed during
an interrupted run and must retain its interrupted status.

Unsuccessful results carry a normalized `error` with `code` and `message`.
Expected codes include `cli_missing`, `invalid_request`,
`unsupported_setting`, `permission_denied`, `auth_required`,
`subscription_required`, `auth_check_failed`, `quota_exceeded`, `provider_error`,
`protocol_error`, `timeout` and `cancelled`. Provider
completion and a usable result are both required for success. Missing or
malformed terminal output produces a protocol failure when no recognized
provider failure explains the exit, even if the process exit code is zero.
A provider may continue after a denied tool call, so one tool denial alone
does not determine the run status.

Raw observations can contain prompts, paths or account information. Keep raw
stderr and provider event payloads out of default diagnostics. Use synthetic
fixtures for parser examples and tests.
