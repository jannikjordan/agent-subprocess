# Provider CLI Proxy integration docs

The Python package is still at the design stage. The
[provider guide](providers.md) records what has been checked against the
official CLIs. There is currently no package to install or import.

| If you need to | Read |
| --- | --- |
| Add analysis, chat or background work to an existing project | [Integration guide](integration.md) |
| Build or consume the Python API | [Session contract](session-contract.md) |
| Check model, effort, permissions and event support | [Provider compatibility](providers.md) |
| Verify library behavior or an app integration | [Verification](verification.md) |

Review the host project's worker, authentication and UI conventions before
integrating. Use its existing queue, access controls and rendering. Once the
package exists, pin a verified revision and check its public exports and
compatibility record before using the examples here. The proxy launches and
observes a local CLI session. The host project decides what work to run and
what to do with the answer.

See the [project vision](../VISION.md) for the delivery order.
