# Provider CLI Proxy

A Python library for running Codex and Claude Code from an existing
application or script. A caller selects the provider, model, effort,
permissions and working directory, then gives the CLI a starting prompt.
The caller can wait for a result or follow the run as it happens. The
library uses the official, installed provider CLIs on the worker host.

## Who uses it

- An embedded assistant sends the current page context and a user's question.
  The web app streams available updates and renders the returned text.
  The app owns chat history, access control and Markdown or rich rendering.
- A script asks a CLI to read and follow `task.md`, or supplies the prompt
  directly. It waits for the final answer and a status it can handle in code.
- A background worker runs a data analysis job in a specified workspace.
  It forwards progress to the calling app and returns text or a validated
  object for the next step. The app owns scheduling, concurrency and retries.

## One session contract

| Part | What the Python caller gets |
| --- | --- |
| Request | Provider, model, effort, working directory, permission settings and a prompt source. Pass literal text, load a trusted prompt file into the request, or send `Read task.md and follow its instructions.` when the CLI should open the file itself. That last form needs permission to read the workspace. |
| Lifecycle | Start a local process, wait for its result, stream its events, or cancel it. A deadline also ends a run. Durable background execution belongs to the caller's worker system. |
| Events | Started, available activity or tool status, user-visible answer updates, optional task reports and a terminal outcome. Advertise whether the provider emits text deltas or complete messages. |
| Result | Terminal status, final text on success, validated structured output when requested, and available metadata such as the native session ID, actual model and usage. Keep diagnostic output distinct from answer text. |

Waiting and streaming observe the same run. The event stream ends with one
terminal outcome, including on timeout or cancellation. Success requires
provider completion and a usable result. Callers can
distinguish missing CLIs, unsupported settings, login or quota failures,
provider or protocol errors, timeouts and cancellation. A session ID is
opaque and provider-specific. Resuming later requires a persistent native
session and an explicit ID. Each job starts fresh by default.

Task reports describe milestones the caller cares about, such as `data_loaded`
or `checks_finished`. They are model-reported and may be absent. The caller
defines the allowed names and fields. Expose validated reports through an
explicit reporting channel when supported. Use a final JSON schema for
machine-readable handoffs. Ordinary prose, incomplete JSON and tool output
remain data. The caller verifies any report that would trigger an action.

## Provider and application boundaries

Use one process runner and a provider adapter for each CLI. The runner owns
subprocess startup, stdout and stderr draining, deadlines and cleanup. An
adapter builds a request from supported settings and translates provider
events into the shared contract. A requested capability without a verified
mapping fails explicitly. Model names and efforts are provider-specific.

The host supplies the installed binary, account setup and workspace. Keep
credentials with the official CLI. Make account or billing-mode changes
explicit caller decisions. A local CLI still sends prompts and any selected
context to its configured provider. Hosted use requires its own review of
provider terms, authentication and tenant isolation. For Claude, Anthropic
describes end-user sign-in in the unmodified CLI and sets separate rules
for developers routing requests on behalf of users. [Claude Code legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)

Default to the access needed for the prompt mode. Deny unattended approval
requests and reject permission policies the adapter cannot enforce before
launch. A `cwd` controls where the process starts,
including for data-only directories outside Git. File, shell, network and
plugin access depend on provider settings and host isolation. Verify
permission claims on each supported CLI and OS, including inherited hooks,
plugins and tool servers.
Pass subprocess arguments directly and keep raw output out of default logs.
The caller validates workspace paths, decides which users can start jobs and
filters what they can see. Treat user input and model output as data at that
boundary.

Later, applications can expose approved web fetch and VM operations through
provider-supported tool integrations. The app selects and authorizes those
capabilities. Queues, agent assignment, remote execution and VM management
belong to the consuming orchestrator.

## Delivery order

1. **Headless jobs.** Import the Python package from another project. Run
   the same small read-only task with both providers in a temporary workspace,
   using inline and file-backed prompts. Confirm model and effort selection,
   final text, live events, and actionable errors. Exercise cancellation,
   deadlines and process cleanup with fake CLIs. Run deterministic tests
   without account access and opt-in compatibility checks with the official
   binaries. Check that restricted runs deny writes and cannot activate
   inherited hooks or MCP servers. Verify the runner on macOS, Windows and
   Linux. Use Haiku for every live Claude Code test.
2. **Assistant and workflow features.** Add explicit resume, native text
   deltas where supported, final JSON Schema output and opt-in live task
   reports. Prove the same package can drive an app's streamed assistant
   and a background worker. Keep the web transport and rendering in the app.
3. **Tool integrations.** Document how a consuming project can enable
   bounded tools and pass visible tool status or validated results through
   the session. Establish the permission boundary before adding examples
   that use a network service or VM.

Maintain a versioned compatibility guide with invocation examples, supported
settings, event samples, permission limits and real-runtime checks. Start
with the Python standard library for process and stream handling. Add a
dependency when a verified need justifies it. Distribute an importable
package without a separate service.

The [integration documentation](docs/README.md) describes the proposed Python
contract and the checks needed before another project can rely on it.

The Corduno documentation assistant is the reference for embedded chat. Its
local bridge uses Codex App Server and Claude Code stream JSON to update the
browser. The [provider compatibility guide](docs/providers.md) records CLI
references and separates the reference app's evidence from this library's
verification. [Corduno documentation provider evidence](https://github.com/getcorduno/documentation/blob/59f041cd0061105c63e58772fa54e1b0d82bbb71/evidence/providers.md)
