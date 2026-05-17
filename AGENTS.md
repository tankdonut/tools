# AGENTS.md

This file defines how automated coding agents should operate in this repository.

For full setup instructions, build details, and usage examples, see `CONTRIBUTING.md`.

## Purpose

Agents working in this repo should make minimal, focused changes that preserve
existing architecture and style. Prefer safe, reviewable workflows. Keep changes
easy to understand and easy to revert.

## Where to Look

| Path | What it is |
|---|---|
| `tasks/metadata.yaml` | Tool definitions: name, version, download URL template, SHA256 |
| `tasks/metadata.schema.json` | JSON schema for validating metadata entries |
| `tasks/tools/` | Invoke tasks: install.py, update.py, digests.py, add.py |
| `tasks/tools/*.py` | Internal modules: `_github.py`, `_metadata.py`, `_install.py`, `_updates.py`, `_automation.py` |
| `tasks/lib/` | Shared libraries: templates.py, platform.py, metadata.py, integrity.py, downloader.py, digests.py |
| `tasks/build.py` | Container image build task |
| `tasks/release.py` | Release automation |
| `tests/` | Test suite: conftest.py fixtures, test_*.py per module |
| `.github/workflows/` | CI/CD: lint, build image, bump versions, prune GHCR |

## Build & Development Commands

### Environment Setup

- `uv sync` - Install dependencies and create virtual environment
- `uv run inv --list` - List all available invoke tasks

### Testing

- `uv run ruff check` - Run linting checks
- `uv run ruff format --check` - Check formatting
- `uv run pytest` - Run all tests with coverage
- `uv run pytest tests/test_update.py` - Run specific test file
- `uv run pytest -k test_name` - Run specific test by name
- `uv run pytest --cov=tasks` - Generate coverage report

### Task Execution

- `uv run inv tools.install --name <tool> --dist` - Install single tool to dist
- `uv run inv tools.install --local` - Install all tools to ~/.local/bin
- `uv run inv tools.update` - Update all tools to latest releases
- `uv run inv tools.update --name <tool>` - Update single tool
- `uv run inv tools.digests` - Fetch SHA256 digests for all tools
- `uv run inv tools.digests --name <tool>` - Fetch digest for a single tool

## Conventions

- Tool metadata lives in `tasks/metadata.yaml` with Jinja2 `download_url` templates
- Binary-only distribution: downloads from upstream GitHub releases, no package managers
- SHA256 integrity verification on install when digest is present; `tools.digests` populates them
- All operations go through Invoke tasks with the `uv run inv` prefix
- Pre-commit hooks run lint and tests automatically

## Environment Configuration

| Variable | Purpose |
|---|---|
| `GITHUB_TOKEN` | GitHub API token for higher rate limits |
| `CONTAINER_REGISTRY` | Override the container image registry |
| `GITHUB_REPOSITORY` | Auto-detected in CI for registry and labels |

## Core Principles

- Be precise and conservative.
- Do not refactor unrelated code.
- Do not introduce new dependencies unless necessary.
- Follow existing patterns before introducing new ones.
- Prefer small, composable changes over large rewrites.

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

## Scope of Authority

Agents MAY:

- Modify existing files in scope of the task
- Run tests, linters, and build commands
- Add tests when behavior intentionally changes
- Fix edge cases that are reasonably inferable from context

Agents MUST NOT:

- Reformat entire files or unrelated identifiers
- Add documentation files unless explicitly requested
- Introduce new dependencies without clear need
- Change public APIs without explicit instruction
- Upgrade existing dependencies unless required for the task
- Remove or skip failing tests to get a green build

## Editing Rules

- Prefer modifying existing files over creating new ones.
- Keep formatting consistent with surrounding code.
- Avoid introducing non-ASCII characters unless already used.
- Only add comments when the code is non-obvious.
- Keep diffs scoped strictly to the task.
- Ensure new code passes linting and tests.
- Prefer clarity over cleverness. Avoid deep nesting.

## Git Workflow

- NEVER run destructive commands (git reset --hard, git checkout --, force push).
- NEVER amend commits unless explicitly instructed.
- NEVER change git config or commit secrets.
- Stage only relevant files.
- Write concise commit messages focused on intent.
- Do not create empty commits or push unless asked.

## Testing and Validation

- Run relevant tests after making changes.
- Update tests only when behavior intentionally changes.
- Aim for 80% code coverage.
- Tests run automatically in pre-commit hooks.

Write tests in `tests/` following pytest conventions. Use fixtures from
`conftest.py` for common setup. Mock external dependencies (GitHub API,
subprocess, file I/O). Use descriptive test names.

## Dependency Management

- Do not upgrade dependencies unless required for the task.
- Avoid adding heavy dependencies for small utilities.
- Prefer standard library solutions where reasonable.

## When in Doubt

- Ask for clarification instead of making assumptions.
- Safety, clarity, and minimal impact are more important than speed.
- If the task is ambiguous, ask. Guessing wastes more time than asking.
