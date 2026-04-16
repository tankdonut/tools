# tools

Collection of CLI tools mostly found on GitHub.

Tracked in `tasks/metadata.yaml`, installed from upstream release binaries,
and optionally packaged into a container image.

## Setup with uv

This project uses `uv` for dependency management and task execution.

Install `uv` (if not already installed):

```bash
curl -Ls https://astral.sh/uv/install.sh | sh
```

Create the virtual environment and install dependencies:

```bash
uv sync
```

List all available tasks:

```bash
uv run inv --list
```

## Install Tools

Install all tools to `dist/` (default):

```bash
uv run inv install
```

Install a single tool to `dist/`:

```bash
uv run inv install --name <tool>
```

Install all tools to `~/.local/bin` (or `~/bin`):

```bash
uv run inv install --local
```

Install a single tool to `~/.local/bin`:

```bash
uv run inv install --name <tool> --local
```

Force reinstall all tools:

```bash
uv run inv install --force
```

Force reinstall a single tool:

```bash
uv run inv install --name <tool> --force
```

The install task:

- Resolves the correct version from `metadata.yaml`
- Renders the `download_url` template for your platform
- Downloads and places the binary in the configured install location

## Adding a New Tool

Add a new entry to `tasks/metadata.yaml` using the `update.add` task:

```bash
uv run inv update.add \
  --repo-url https://github.com/owner/repo \
  --download-url "{{repo_url}}/releases/download/v{{version}}/{{name}}-{{os}}-{{arch}}" \
  --license MIT \
  --description "Short tool description"
```

Options:

- `--name` — Override the inferred tool name
- `--dry-run` — Preview the generated entry without writing changes

The command will fail if the tool name already exists.

This task:

- Fetches the latest GitHub release from the provided `repo_url`
- Infers the tool name from the repository if `--name` is not provided
- Extracts and normalizes the semantic version (strips leading `v`)
- Inserts the tool into `metadata.yaml`
- Keeps entries in strict alphanumeric order
- Validates against `metadata.schema.json`

## Updating Existing Tools

Update all tools to their latest GitHub release:

```bash
uv run inv update.tools
```

Update a single tool:

```bash
uv run inv update.tool --name <tool>
```

Preview updates without writing changes:

```bash
uv run inv update.tools --dry-run
uv run inv update.tool --name <tool> --dry-run
```

Adjust the release age filter (default is 7 days):

```bash
uv run inv update.tools --cooldown 14
uv run inv update.tool --name <tool> --cooldown 14
```

These commands:

- Query the latest GitHub release
- Compare against the current version
- Update `metadata.yaml` if a newer semantic version is found
- Skip releases younger than the cooldown period
- Preserve strict alphanumeric ordering

## Automation

Run full update automation with automatic PR creation and auto-merge:

```bash
uv run inv update.automation
```

Options:

- `--ci` — Indicates execution in a CI environment
- `--dry-run` — Preview actions without making changes
- `--cooldown` — Release age filter in days (default: 7)

This task:

- Detects all available updates across tracked tools
- Creates a feature branch (`automation/update-<timestamp>`)
- Commits version changes to `metadata.yaml`
- Opens a pull request against `main` with a summary of changes
- Labels the PR with `dependencies`
- Enables auto-merge (respects branch protection rules)
- Reports skipped releases that are too young

A scheduled GitHub Actions workflow runs this weekly (Sundays at 03:00 UTC).

## Container Image

Build a container image with all tools pre-installed:

```bash
uv run inv build.container
```

Push the image to a registry:

```bash
uv run inv build.container --push
```

Options:

- `--registry` — Target registry (default: `ghcr.io/$GITHUB_REPOSITORY`)
- `--tag` — Image tag (default: current git SHA)
- `--push` — Push the image after building

The `build.container` task auto-detects `podman` or `docker` and builds
using the Containerfile, which uses a multi-stage build producing a minimal
`scratch` image with all binaries under `/dist`.

When run on the `main` branch (detected via `GITHUB_REF`), the build
automatically tags and pushes a `:latest` image alongside the SHA-tagged one.

## Download URL Template Variables

The `download_url` field is rendered using Jinja. Common variables:

| Variable       | Description                                         |
|----------------|-----------------------------------------------------|
| `{{name}}`     | The tool name                                       |
| `{{version}}`  | Resolved semantic version                           |
| `{{repo_url}}` | Repository URL from metadata                        |
| `{{os}}`       | Target operating system                             |
| `{{arch}}`     | Target architecture (Go-style)                      |
| `{{rust_arch}}`| Rust-style architecture (when required by upstream) |

Refer to existing entries in `tasks/metadata.yaml` for patterns.

## Environment Variables

| Variable              | Description                                  |
|-----------------------|----------------------------------------------|
| `GITHUB_TOKEN`        | GitHub API token (increases rate limits)     |
| `CONTAINER_REGISTRY`  | Override the container image registry        |
| `GITHUB_REPOSITORY`   | Auto-detected in CI for registry and labels  |

Copy `.env.example` to `.env` for local configuration.

## CI/CD

GitHub Actions workflows:

| Workflow                          | Trigger                                        | Description                              |
|-----------------------------------|------------------------------------------------|------------------------------------------|
| `lint-and-test.yaml`              | Push to `main`, pull requests                  | Runs pre-commit hooks (lint, tests)      |
| `build-and-publish-image.yaml`    | Push to `main`, pull requests, manual          | Builds and pushes container to GHCR      |
| `bump-tool-versions.yaml`         | Weekly schedule (Sundays 03:00), manual        | Runs `update.automation` for tool bumps  |
| `prune-ghcr-images.yaml`          | Daily schedule (01:30 UTC), manual             | Removes stale GHCR images                |

## Development

Install pre-commit hooks:

```bash
pre-commit install
```

Run linting:

```bash
uv run ruff check
uv run ruff format --check
```

Run tests:

```bash
uv run pytest
uv run pytest tests/test_update.py
uv run pytest -k test_name
```

Generate coverage report:

```bash
uv run pytest --cov=tasks
uv run pytest --cov=tasks --cov-report=html
```

## License

[MIT](LICENSE)
