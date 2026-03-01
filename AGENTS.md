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

## Build & Development Commands

### Environment Setup

- `uv sync` - Install dependencies and create virtual environment
- `uv run inv --list` - List all available invoke tasks

### Testing

- `uv run ruff check` - Run linting checks
- `uv run ruff format --check` - Check formatting
- `python scripts/test_update_automation_dry_run.py` - Run update automation tests
- Individual tests: Run specific test files directly with `python`

### Task Execution

- `uv run inv install.all` - Install all tools
- `uv run inv install.package --name <package>` - Install single tool
- `uv run inv update.update-all` - Update all tools to latest releases
- `uv run inv update.package --name <package>` - Update single package

---

## General Principles

- Be precise and conservative.
- Do not refactor unrelated code.
- Do not introduce new dependencies unless necessary.
- Follow existing patterns before introducing new ones.
- Prefer small, composable changes over large rewrites.

If something is unclear, ask instead of guessing.

---

## Code Style Guidelines

### Python Style

- **Line length**: 100 characters (enforced by ruff)
- **Type hints**: Required for all function parameters and return values
- **Imports**: Use absolute imports only (relative imports banned)
- **Sorting**: Force sort within sections, no trailing comma splitting
- **File paths**: Use `pathlib.Path` instead of `os.path`
- **Subprocess**: Use `subprocess.run()` for command execution
- **Configuration**: Use YAML for structured data, Jinja2 for templating

### Linting Rules (Ruff)

Enabled rule sets: F, E, I, N, UP, RUF, B, C4, ISC, PIE, PT, PTH, SIM, TID
Ignored: RUF005, RUF012
Unfixable: F401 (unused imports - only fix in nox/editor context)

### Naming Conventions

- **Functions**: `snake_case` (e.g., `get_goarch()`)
- **Variables**: `snake_case` (e.g., `machine_arch`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `ROOT_DIR`)
- **Classes**: `PascalCase` (e.g., `BaseLoader`)

### Error Handling

- Use specific exception types with descriptive messages
- Include context in error messages (e.g., `f"Unsupported architecture: {arch}"`)
- Validate inputs early and fail fast

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

- Preserve existing public APIs unless explicitly changing them.
- Avoid breaking changes unless requested.
- Ensure new code compiles and passes tests.
- Handle edge cases if they are reasonably inferable.
- Prefer clarity over cleverness and avoid deep nesting.

---

## Testing and Validation

- Run relevant tests after making changes.
- Update tests only when behavior intentionally changes.
- Avoid introducing a test framework unless requested.

---

## Git Safety Rules

- NEVER run destructive commands (git reset --hard, git checkout --, force push).
- NEVER amend commits unless explicitly instructed.
- NEVER change git config or commit secrets.

When committing:

- Stage only relevant files.
- Write concise commit messages focused on intent.
- Do not create empty commits or push unless asked.

---

## Dependency Management

- Do not upgrade dependencies unless required for the task.
- Avoid adding heavy dependencies for small utilities.
- Prefer standard library solutions where reasonable.

---

## Scope Discipline

Avoid reformatting entire files or unrelated identifiers.
Keep diffs tight and review-friendly.

---

## When in Doubt

Ask for clarification instead of making assumptions.
Safety, clarity, and minimal impact are more important than speed.
