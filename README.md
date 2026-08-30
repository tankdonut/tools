# tools

CLI tools tracked in `tasks/metadata.yaml`, installed from upstream release binaries, and optionally
packaged into a container image.

## Quick Start

```bash
curl -Ls https://astral.sh/uv/install.sh | sh
uv sync
```

```bash
uv run inv tools.install                # all tools to dist/
uv run inv tools.install --name <tool>  # single tool to dist/
uv run inv tools.install --local        # all tools to ~/.local/bin
uv run inv tools.install --force        # force reinstall
```

## Download URL Template Variables

The `download_url` field uses Jinja templates. See `tasks/metadata.yaml` for examples.

| Variable        | Description                                          |
|-----------------|------------------------------------------------------|
| `{{name}}`      | Tool name                                            |
| `{{version}}`   | Resolved semantic version                            |
| `{{repo_url}}`  | Repository URL from metadata                         |
| `{{os}}`        | Target operating system                              |
| `{{arch}}`      | Target architecture (Go-style)                       |
| `{{rust_arch}}` | Rust-style architecture (when required by upstream)  |

## Environment Variables

| Variable             | Description                                 |
|----------------------|---------------------------------------------|
| `GITHUB_TOKEN`       | GitHub API token (increases rate limits)    |
| `CONTAINER_REGISTRY` | Override the container image registry       |
| `GITHUB_REPOSITORY`  | Auto-detected in CI for registry and labels |

Copy `.env.example` to `.env` for local configuration.

## CI/CD

| Workflow                        | Trigger                                   | Description                           |
|---------------------------------|-------------------------------------------|---------------------------------------|
| `lint-and-test.yaml`            | Push to `main`, pull requests             | Runs pre-commit hooks (lint, tests)   |
| `build-and-publish-image.yaml`  | Push to `main`, pull requests, manual     | Builds and pushes container to GHCR   |
| `bump-tool-versions.yaml`       | Weekly schedule (Sundays 03:00), manual   | Runs `tools.update --pr` for bumps    |
| `release.yaml`                  | Push to `main` (tool version changes), manual | Cuts CalVer tag, creates release, tags image, updates changelog |
| `prune-ghcr-images.yaml`        | Daily schedule (01:30 UTC), manual        | Removes stale GHCR images             |

## Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) for adding tools, updating versions, digests, container builds,
  and development setup
- [AGENTS.md](AGENTS.md) for build commands, code style, and testing reference

## License

[MIT](LICENSE)
