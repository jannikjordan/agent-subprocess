# Provider CLI Proxy integration docs

Install the package and try the offline example from the
[project README](../README.md). The [provider guide](providers.md) records
which features have been checked against the official CLIs.

| If you need to | Read |
| --- | --- |
| Add analysis, chat or background work to an existing project | [Integration guide](integration.md) |
| Build or consume the Python API | [Session contract](session-contract.md) |
| Check model, effort, permissions and event support | [Provider compatibility](providers.md) |
| Verify library behavior or an app integration | [Verification](verification.md) |
| Pin an upgrade or report an integration problem | [Versions and issues](versioning.md) |

Review the host project's worker, authentication and UI conventions before
integrating. Use its existing queue, access controls and rendering. Pin a
verified revision and check its compatibility record. The proxy launches and
observes a local CLI session. The host project decides what work to run and
what to do with the answer.

See the [project vision](../VISION.md) for the delivery order.
