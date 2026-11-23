# Changelog

## 0.2.1

- Publish a GitHub source tag and release notes automatically after an
  approved version bump reaches `main`.
- This first tagged release includes cross-platform CLI discovery,
  subscription checks, provider inventory and the offline example.

## 0.2.0

- Discover supported Codex and Claude Code installations through PATH and
  known native, Homebrew, WinGet, npm and macOS desktop layouts.
- Check subscription sign-in before sending a prompt. Distinguish missing
  sign-in, unsupported account types and unavailable status.
- Report installed CLI paths, versions, sign-in state and available quota
  windows through `Client.list_providers()`.
- Run Python sessions on Windows with a Win32 Job Object for process-tree
  cleanup. Prompt files and offline examples work on macOS, Windows and Linux.

## 0.1.0

- Run pinned Codex and Claude Code CLIs from Python on macOS and Linux.
- Stream activity and answer updates, wait for the terminal result, and
  cancel or time out a run.
- Support inline and file-backed prompts, with `workspace_read` on verified
  macOS CLI versions. Include an offline integration example.
