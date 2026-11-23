# Python session contract

Proposed public API. Names and behavior below need implementation and
release verification. See the [vision](../VISION.md#delivery-order) for which
features are planned first.

## Request

| Field | Meaning |
| --- | --- |
| `provider` | `codex` or `claude` |
| `model`, `effort` | Provider-specific values. Omission delegates the choice to that provider. An explicit unsupported choice fails. |
| `cwd` | An existing host directory selected by the caller. Relative paths inside the task resolve from this workspace. |
| `permissions` | The requested capabilities. `prompt_only` disables host tools. `workspace_read` permits agent reads of files within the caller-approved workspace and denies writes and agent-initiated network access. Refuse a profile before launch if the adapter cannot enforce it. The CLI's own provider connection remains available. |
| `prompt` | One starting prompt. `Prompt.text(...)` carries text. `Prompt.from_file(...)` loads a UTF-8 file using the application's access before starting a provider process. |
| `deadline_seconds` | Positive time limit for the run, including startup. Terminal completion follows cleanup. |
| `resume_session_id` | Later. Explicit native ID from a persisted session under the same provider and compatible host configuration. Omission starts a fresh session. |
| `output_schema`, `report_schema` | Later. Final JSON Schema and an optional definition of permitted live reports. Unsupported schemas fail explicitly. |

Pass an instruction like `Read task.md and follow its instructions.` as text
when the provider should open the file itself. The application approves the
workspace and the requested permission profile independently of prompt text.

## Run and cancellation

- `Client()` creates a client. `await client.run(request)` waits for a
  `RunResult` without requiring a streaming consumer.
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
  without reading events must still be able to finish. Stream limits and
  overflow must have explicit behavior. Cancellation and deadline handling
  stop the managed process, clean up its subprocesses within host support,
  and resolve the same terminal outcome for both readers.

## Events and results

Each event has a run ID, a provider, a kind and a per-run sequence number.
Sequence gives the order observed by the proxy. The event stream ends with
one `finished` event carrying a `RunResult`, including when startup fails.

| Event | Meaning |
| --- | --- |
| `started` | The provider process started. Native session metadata can arrive later. |
| `activity` | Available user-visible work status from the runtime, such as a tool starting or completing. |
| `answer_delta` | Append this text to the current response. Produced by a transport that exposes text deltas. |
| `answer_snapshot` | Replace the current response with this complete text. Used for completed messages or to reconcile the displayed answer. |
| `report` | Later. A model-reported milestone from an explicit channel with schema-validated fields. The application decides whether the reported claim is sufficient evidence. |
| `finished` | Terminal result. The successful final text in the result is authoritative. |

`RunResult` includes the run ID, provider and a `status` of `succeeded`,
`failed`, `timed_out` or `cancelled`. A successful result carries `text`
and, when requested and supported, validated `structured_output`.
Provider metadata such as `native_session_id`,
`actual_model` and `usage` is optional. Requested values remain distinguishable
from values observed in provider output. Partial text can be displayed during
an interrupted run and must retain its interrupted status.

Unsuccessful results carry a normalized `error` with a code and a safe
summary. Expected codes include `cli_missing`, `invalid_request`,
`unsupported_setting`, `permission_denied`, `auth_required`, `quota_exceeded`,
`provider_error`, `protocol_error`, `timeout` and `cancelled`. Provider
completion and a usable result are both required for success. Missing or
malformed terminal output produces a protocol failure when no recognized
provider failure explains the exit, even if the process exit code is zero.
A provider may continue after a denied tool call, so one tool denial alone
does not determine the run status.

Raw observations can contain prompts, paths or account information. Keep raw
stderr and provider event payloads out of default diagnostics. Use synthetic
fixtures for parser examples and tests.
