# Contributing

This guide covers development setup and task usage for the tools repository.

## Development Environment

Prerequisites:

- git
- [uv](https://docs.astral.sh/uv/) for dependency management
- podman or docker (optional, for container builds)

Initial setup:

```bash
curl -Ls https://astral.sh/uv/install.sh | sh
uv sync
uv run inv --list
```

Install pre-commit hooks:

```bash
uv run pre-commit install
```

Environment variables used across tasks:

| Variable              | Description                                  |
|-----------------------|----------------------------------------------|
| `GITHUB_TOKEN`        | GitHub API token (increases rate limits)     |
| `CONTAINER_REGISTRY`  | Override the container image registry        |
| `GITHUB_REPOSITORY`   | Auto-detected in CI for registry and labels  |

Copy `.env.example` to `.env` for local configuration.

## Install Tasks

Install all tools to `dist/`:

```bash
uv run inv tools.install
```

Install a single tool:

```bash
uv run inv tools.install --name <tool>
```

Install all tools to `~/.local/bin` (or `~/bin`):

```bash
uv run inv tools.install --local
```

Install a single tool to `~/.local/bin`:

```bash
uv run inv tools.install --name <tool> --local
```

Force reinstall all tools, or a single one:

```bash
uv run inv tools.install --force
uv run inv tools.install --name <tool> --force
```

The install task resolves the version from `metadata.yaml`, renders the
`download_url` template for your platform, and downloads the binary to the
configured location.

## Adding a New Tool

```bash
uv run inv tools.add \
  --repo-url https://github.com/owner/repo \
  --download-url "{{repo_url}}/releases/download/v{{version}}/{{name}}-{{os}}-{{arch}}" \
  --license MIT \
  --description "Short tool description"
```

Options:

- `--name` — Override the inferred tool name
- `--dry-run` — Preview the generated entry without writing changes

The command fails if the tool name already exists. It fetches the latest
GitHub release, infers the name from the repository, extracts and normalizes
the semantic version, inserts the entry in alphanumeric order, and validates
against `metadata.schema.json`.

The `download_url` field is rendered using Jinja. Common variables:

| Variable        | Description                                          |
|-----------------|------------------------------------------------------|
| `{{name}}`      | The tool name                                        |
| `{{version}}`   | Resolved semantic version                            |
| `{{repo_url}}`  | Repository URL from metadata                         |
| `{{os}}`        | Target operating system                              |
| `{{arch}}`      | Target architecture (Go-style)                       |
| `{{rust_arch}}` | Rust-style architecture (when required by upstream)  |

Refer to existing entries in `tasks/metadata.yaml` for patterns.

## Update Tasks

Update all tools to their latest GitHub release:

```bash
uv run inv tools.update
```

Update a single tool:

```bash
uv run inv tools.update --name <tool>
```

Preview updates without writing changes:

```bash
uv run inv tools.update --dry-run
uv run inv tools.update --name <tool> --dry-run
```

Adjust the release age filter (default is 7 days):

```bash
uv run inv tools.update --cooldown 14
uv run inv tools.update --name <tool> --cooldown 14
```

These commands query the latest GitHub release, compare against the current
version, and update `metadata.yaml` if a newer version is found. Releases
younger than the cooldown period are skipped. Alphanumeric ordering is
preserved.

## Automated Updates with PRs

```bash
uv run inv tools.update --pr
```

Options:

- `--pr` — Create a pull request and enable auto-merge after approval
- `--dry-run` — Preview actions without making changes
- `--cooldown` — Release age filter in days (default: 7)

This task detects updates across all tracked tools, creates a feature branch
(`automation/update-<timestamp>`), commits version changes to
`metadata.yaml`, opens a PR against `main`, labels it with `dependencies`,
and enables auto-merge (respecting branch protection rules). Releases too
young for the cooldown window are reported as skipped.

A scheduled GitHub Actions workflow runs this weekly (Sundays at 03:00 UTC).

### Workflow Token (`BUMP_PAT`)

The scheduled `bump-tool-versions` workflow authenticates with a dedicated
personal access token stored as the repository secret `BUMP_PAT`, rather than
the default `GITHUB_TOKEN`. A separate PAT is required because pull requests
opened by the default token do not trigger downstream `pull_request`
workflows, so the bump PR's lint and test checks would never run.

The token backs these operations performed by `tools.update --pr`:

- Push the `automation/update-*` branch to the repository
- Read upstream GitHub Releases for latest versions and asset digests
- Create, list, label, and enable auto-merge on the pull request

Create a fine-grained PAT scoped to this repository with these repository
permissions:

| Permission     | Access          | Used for                                                |
|----------------|-----------------|---------------------------------------------------------|
| Contents       | Read and write  | Push the update branch; read release versions and digests |
| Pull requests  | Read and write  | Create the PR, list existing PRs, enable auto-merge     |
| Issues         | Read and write  | Add the `dependencies` label to the PR                  |
| Metadata       | Read            | Required baseline (auto-granted)                        |

Store the token under **Settings → Secrets and variables → Actions** as
`BUMP_PAT`. A classic PAT with the `repo` scope also works but grants broader
access than necessary; prefer the fine-grained token above.

## SHA256 Integrity Verification

When a `sha256` field is present in a tool's metadata, the install task
verifies the downloaded file against the expected hash before extraction. If
the hash does not match, the download is deleted and an `IntegrityError` is
raised. Tools without a `sha256` field install normally with no verification.

Fetch digests for all tools, or a single one:

```bash
uv run inv tools.digests
uv run inv tools.digests --name <tool>
```

The `tools.digests` task populates `sha256` values by querying the GitHub
Release Asset API `digest` field first, falling back to checksum files
(checksums.txt, SHA256SUMS, etc.) in release assets. HashiCorp tools get
special handling via releases.hashicorp.com. asdf is skipped (only MD5
available).

## Container Image Tasks

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

The task auto-detects `podman` or `docker` and builds using the
Containerfile. The build is multi-stage, producing a minimal `scratch` image
with all binaries under `/dist`. On the `main` branch (detected via
`GITHUB_REF`), the build automatically tags and pushes a `:latest` image
alongside the SHA-tagged one.

## Linting and Tests

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

Generate coverage reports:

```bash
uv run pytest --cov=tasks
uv run pytest --cov=tasks --cov-report=html
```

## Key Expectations

- Be precise and conservative with changes
- Do not refactor unrelated code
- Follow existing patterns before introducing new ones
- Prefer small, composable changes over large rewrites
- If something is unclear, ask instead of guessing

## Git Conventions

- Write concise commit messages focused on intent
- Stage only relevant files
- Do not force push or amend unless instructed
- Do not commit secrets
