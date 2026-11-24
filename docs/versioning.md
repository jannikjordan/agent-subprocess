# Versions and issues

## Pin a version

Until the first Agent Subprocess release, install from a reviewed commit on
`dev`. The existing `v0.2.1` release uses the earlier package name. Check
the release notes for a tag that installs `agent-subprocess` and imports
`agent_subprocess`. [GitHub releases](https://github.com/jannikjordan/provider-cli-proxy/releases)

```sh
python -m pip install "git+https://github.com/jannikjordan/provider-cli-proxy.git@COMMIT_SHA"
```

Replace `COMMIT_SHA` with the full revision. Once the renamed package has
a release, you can use its tag in place of the SHA.

The package version in `pyproject.toml` tracks the Python API. CLI
compatibility is a separate pin in the [provider guide](providers.md).
Check both when upgrading.

## Report bugs and request changes

If you are an agent integrating this library and need a feature, want to
extend its public API or encounter a bug, search the existing issues and
open an issue in the library repository. Link it from your consuming
project so both projects can track the work. [Open an issue](https://github.com/jannikjordan/provider-cli-proxy/issues/new)

Include the package version or commit, provider CLI version, OS, installer,
expected behavior and a small reproduction using synthetic data. For feature
requests, describe the API behavior you need and the consuming workflow.
Share safe error codes. Keep credentials, account identifiers and private
prompts out of issues.

## Release notes

- Add public changes to the [changelog](../CHANGELOG.md) with the change.
  Use `Unreleased` between release preparations.
- Choose the next version in `pyproject.toml` and the changelog in the
  release PR. During `0.x`, use a minor version for new API behavior or
  breaking changes and a patch for compatible fixes. Call out changes that
  require a consuming project to adapt.
- Cut a short-lived release branch from tested `dev` and open a PR into
  `main`. It runs the three platform checks. After the owner approves and
  merges it, the release workflow tags the merged commit `vX.Y.Z` and
  publishes that version's changelog entry in GitHub Releases.
- Each version publishes once. If publishing fails, inspect the run and
  rerun it on the same commit. The job can reuse a tag at that commit from
  a partial run. It stops if the tag points elsewhere.
- Consumers install from Git tags. The checks build and install the package
  for verification. The workflow publishes a source tag and release notes on GitHub.
