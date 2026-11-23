# Versions and issues

## Pin a version

Pick an approved version in [Releases](https://github.com/jannikjordan/provider-cli-proxy/releases)
and install its tag. Replace `vX.Y.Z` with the tag you selected.

```sh
python -m pip install "git+https://github.com/jannikjordan/provider-cli-proxy.git@vX.Y.Z"
```

Use a full reviewed commit SHA for a development build. The package version
in `pyproject.toml` tracks the Python API. CLI compatibility is a separate
pin in the [provider guide](providers.md). Check both when upgrading.

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
- A release PR targets `main` and runs the three platform workflows. After
  owner approval and merge, the owner tags the commit `vX.Y.Z`. The GitHub
  release notes use that version's changelog entry.
- Consumers install from Git tags. Release checks build and install the
  package during verification. The tag and notes are the distribution for
  this private library.
