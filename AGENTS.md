# AGENTS.md

This file defines how automated coding agents should operate in this repository.

## Purpose

Agents are expected to:

- Make minimal, focused changes
- Preserve existing architecture and style
- Avoid destructive git operations
- Prefer safe, reviewable workflows

Keep changes easy to understand and easy to revert.

---

## General Principles

- Be precise and conservative.
- Do not refactor unrelated code.
- Do not introduce new dependencies unless necessary.
- Follow existing patterns before introducing new ones.
- Prefer small, composable changes over large rewrites.

If something is unclear, ask instead of guessing.

---

## File Editing Rules

- Prefer modifying existing files over creating new ones.
- Do not add documentation files unless explicitly requested.
- Keep formatting consistent with surrounding code.
- Avoid introducing non-ASCII characters unless already used.
- Only add comments when the code is non-obvious.
- Do not reformat entire files unless explicitly requested.
- Keep diffs scoped strictly to the task.

---

## Code Quality Expectations

Agents should:

- Preserve existing public APIs unless explicitly changing them.
- Avoid breaking changes unless requested.
- Ensure new code compiles and passes tests where applicable.
- Handle edge cases if they are reasonably inferable.
- Avoid premature abstraction.

When adding logic:

- Prefer clarity over cleverness.
- Avoid deep nesting.
- Keep functions small and focused.

---

## Testing and Validation

If tests exist:

- Run relevant tests after making changes.
- Update tests only when behavior intentionally changes.
- Do not weaken assertions to make tests pass.

If no tests exist:

- Avoid introducing a test framework unless requested.
- Consider adding small, local validation only if clearly beneficial.

---

## Git Safety Rules

Agents must:

- NEVER run destructive commands (git reset --hard, git checkout --, force push).
- NEVER amend commits unless explicitly instructed.
- NEVER change git config.
- NEVER commit secrets (.env files, credentials, API keys).

If committing:

- Stage only relevant files.
- Write concise commit messages focused on intent.
- Do not create empty commits.
- Do not push unless explicitly asked.

If the working tree is dirty:

- Do not revert unrelated user changes.
- Ignore unrelated modified files.
- Do not "clean up" unrelated formatting issues.

---

## Dependency Management

- Do not upgrade dependencies unless required for the task.
- Do not modify lockfiles unless dependencies change.
- Avoid adding heavy dependencies for small utilities.
- Prefer standard library solutions where reasonable.

---

## Performance and Security

Agents should:

- Avoid obvious performance regressions.
- Avoid introducing blocking or synchronous work in hot paths.
- Validate external inputs where appropriate.
- Avoid logging sensitive data.

If a change has security implications, note it clearly in the commit or PR description.

---

## Pull Requests

When creating a PR:

- Include a short summary explaining why the change exists.
- Explain behavioral changes clearly.
- Avoid describing only file changes — explain intent.
- Ensure only relevant commits are included.
- Keep PRs focused and reasonably small.

---

## Scope Discipline

Agents should avoid:

- Reformatting entire files
- Renaming unrelated identifiers
- Updating build systems without reason
- Introducing stylistic changes outside the touched area
- Large-scale refactors without explicit approval

Keep diffs tight and review-friendly.

---

## Communication Guidelines

When interacting with users:

- Be concise and direct.
- State what changed and why.
- Reference modified files explicitly.
- Suggest logical next steps when appropriate.
- Ask clarifying questions if requirements are ambiguous.

Do not overwhelm with unnecessary detail.

---

## When in Doubt

Ask for clarification instead of making assumptions.
Safety, clarity, and minimal impact are more important than speed.
