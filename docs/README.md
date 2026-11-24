# Agent Subprocess documentation

Start with the [offline example](../examples/analysis_job/README.md).
It loads a file, starts a fake CLI and prints the result. Use it to check
your Python setup before signing in to a provider.

| Task | Guide |
| --- | --- |
| Call the library from a script, personal assistant or job worker | [Integration guide](integration.md) |
| Look up request fields, events and error codes | [Python session contract](session-contract.md) |
| Check CLI versions, installation paths or permission modes | [Provider compatibility](providers.md) |
| Test a change or a consuming project | [Verification](verification.md) |
| Pin a revision, report a bug or prepare a release | [Versions and issues](versioning.md) |

## For integration agents

1. Read the host project's instructions and check the
   [personal-use scope](../README.md#personal-use).
2. Pin a reviewed revision and use the public imports from
   `agent_subprocess`. Match the provider executable to the compatibility
   table before writing live checks.
3. Start with `Client.run()` and the default `prompt_only` profile. Add
   streaming or workspace access only when the host project needs it.
   The host chooses the workspace and owns job scheduling and rendering.
4. Test with fixture processes and synthetic data first. Check the terminal
   result before using the answer and keep account data out of logs and issues.

[Project vision](../VISION.md) · [Maintenance instructions](../AGENTS.md)
