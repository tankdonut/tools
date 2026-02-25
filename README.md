# tools

Collection of tools mostly found on GitHub.

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

Run tasks via `uv`:

```bash
uv run inv --list
```

## Install Tools

Install all tools:

```bash
uv run inv install.all
```

Install a single tool:

```bash
uv run inv install.package --name <package>
```

These tasks:

- Resolve the correct version from `metadata.yaml`
- Render the `download_url` template for your platform
- Download and place the binary in the configured install location

## Update Metadata

### Add a New Tool

```bash
uv run inv update.add \
  --repo-url https://github.com/owner/repo \
  --download-url "{{repo_url}}/releases/download/v{{version}}/{{name}}-{{os}}-{{arch}}" \
  --license MIT \
  --description "Short tool description"
```

Optional:

- `--name` Override the inferred package name
- `--dry-run` Preview the generated entry without writing changes

The command will fail if the package name already exists.

## Adding a New Tool

You can automatically add a new entry to `tasks/metadata.yaml` using the `update.add` task.

This task:

- Fetches the latest GitHub release from the provided `repo_url`
- Infers the tool name from the repository if `--name` is not provided
- Extracts and normalizes the semantic version (strips leading `v`)
- Inserts the tool into `metadata.yaml`
- Keeps entries in strict alphanumeric order
- Validates against `metadata.schema.json`

### Download URL Template Variables

The `download_url` field is rendered using Jinja. Common variables:

- `{{name}}` The package name
- `{{version}}` Resolved semantic version
- `{{repo_url}}` Repository URL from metadata
- `{{os}}` Target operating system
- `{{arch}}` Target architecture
- `{{rust_arch}}` Rust-style architecture (when required by upstream releases)

Refer to existing entries in `tasks/metadata.yaml` for patterns.

## Updating Existing Tools

To update all tools to their latest GitHub release:

```bash
uv run inv update.update-all
```

To update a single package:

```bash
uv run inv update.package --name <package>
```

To preview updates without writing changes:

```bash
uv run inv update.update-all --dry-run
```

These commands:

- Query the latest GitHub release
- Compare against the current version
- Update `metadata.yaml` if a newer semantic version is found
- Preserve strict alphanumeric ordering

This ensures the correct Python environment and pinned dependencies are used.
