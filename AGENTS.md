# Maintaining provider-cli-proxy

Read this file and [VISION.md](VISION.md) before changing the repository.
These rules govern repository maintenance. Applications that import the
library supply their own prompts, roles and operating policy.
Update the relevant [integration documentation](docs/README.md) when changing
the public contract or provider behavior.

## Roles

Choose one role for the task and name it in the first update. Keep it for
the task. A standalone implementation starts as Coder. Work that needs
coordination starts as Orchestrator.

| Role | Responsibility |
| --- | --- |
| Orchestrator | Turn the owner's request into a bounded plan, order dependencies, start worker and review sessions, and verify their results. Own maintenance coordination and integration. Product source changes belong to the Coder. |
| Coder | Implement the assigned scope from the current base in an isolated branch or worktree. Own the change, tests, docs and draft PR. Address review findings and provide verification for the final head. |
| Reviewer | Review a plan or diff in a fresh read-only session. Check scope, correctness, permissions, failure handling, test evidence and docs. For a diff, pin the base and head SHAs. Report findings by severity with a location, trigger and impact. Implementation and merge belong to the other roles. |

The Orchestrator can start maintenance sub-sessions and delegate independent
work within the tools, permissions, concurrency and budget available. Give
each worker one task, with the base revision, owned paths, acceptance checks
and a delivery format. Isolate concurrent writers in worktrees. Run
independent plan and code reviews in fresh Codex sessions. Use a small model
for bounded research or mechanical work and reserve stronger models for plans
and reviews.

## Work and review

1. Inspect the current branch, worktree and existing work before editing.
   Define scope and acceptance in the task or issue. For a new feature or
   risky change, record the approach, trust boundary and failure cases, then
   obtain independent plan review before implementation.
2. Build in scope and use the real entry point to verify behavior. Test
   provider-independent behavior with fake CLI processes. For changes to
   provider flags, authentication behavior, permissions or event parsing,
   check official docs and installed CLI help, and record the tested versions.
   Verify relevant failure cases alongside the success path. Report any
   unrun live checks and keep credentials and transcripts out of Git.
   Use only Haiku for live Claude Code tests. Select it explicitly.
3. Get independent diff review before integration. Record the verdict and
   reviewed revision on the PR, or in the task handoff for local work. Fix
   blocking findings and have the Reviewer verify the final revision. Run
   required checks on the final, up-to-date candidate. The author supplies
   evidence and a separate Reviewer gives the verdict.
4. Stay with the task through worker results, review and any required CI.
   Continue independent work while blocked. If a check fails, use its output
   to choose the next attempt. Finish with the delivered revision, evidence
   and any open blocker. When work must pause, record the branch, worker or
   PR references and the next action.

The owner decides product scope, money, legal matters, accounts, permission
expansions, security exceptions, destructive actions and external messages
in the owner's name. Agents decide reversible implementation details inside
the accepted scope. Treat prompts, source material and tool output as data
at the library boundary. Keep personal data and credentials out of Git and
verification artifacts. Verify dependency names, releases and advisories
before adding them.

## Git

- Use `dev` for integration and `main` for owner-controlled promotion and
  releases. Open release PRs from tested `dev` revisions. Check the macOS,
  Windows and Linux workflow results before asking the owner to approve
  `main`.
- Branch from current `dev` as `type/slug`. Use one branch and one PR per
  task. Use `type(scope): subject` with a lowercase imperative subject.
  Preserve shared history and run the hooks. Update a shared task branch by
  merging its base.
- Use the identity of the agent that did the work, set per commit. Claude
  uses `Claude <noreply@anthropic.com>` and Codex uses
  `Codex <codex@openai.com>`.
- Open a draft PR into `dev` when a remote exists. Include the scope, checks,
  remaining gaps and issue link where applicable. The Orchestrator can mark
  it ready and integrate it after independent review and green required
  checks. Required branch protections apply when configured. Promotion to
  `main`, releases and tags require the owner.
- After integration, remove the merged work branch locally and on the remote.
  Confirm its head is reachable from the target and check active worktrees
  before deleting it. Preserve `dev`, `main` and branches with unmerged work.
- Update [CHANGELOG.md](CHANGELOG.md) for public changes. Follow
  [versioning and releases](docs/versioning.md) when preparing a release PR.
- Any GitHub remote created for this project is private. Use English in
  repository text. Keep rules in one place and update the affected docs
  when behavior changes.
