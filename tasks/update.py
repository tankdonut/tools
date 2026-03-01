from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlparse

from invoke.tasks import task
from jinja2 import Environment, FileSystemLoader, select_autoescape
from jsonschema import validate
import requests
import requests.exceptions
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
import semver
import tenacity

from tasks.lib import METADATA_FILE, METADATA_SCHEMA_FILE, MetadataCache

metadata_cache = MetadataCache()


class AutomationError(Exception):
    """Base exception for automation errors."""


class GitHubRateLimitError(AutomationError):
    """GitHub API rate limit exceeded."""


class GitOperationError(AutomationError):
    """Git operation failed."""

    def __init__(self, command: tuple[str, ...] | list[str], stderr: str):
        self.command = command
        self.stderr = stderr
        super().__init__(f"Git command failed: {' '.join(command)}\n{stderr}")


TEMPLATE_DIR = Path(METADATA_FILE).parent
TEMPLATE_NAME = "metadata.yaml.j2"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(disabled_extensions=("yml", "yaml", "jinja2", "j2")),
    trim_blocks=True,
    lstrip_blocks=True,
)

template = env.get_template(TEMPLATE_NAME)


def safe_git_command(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run git command with proper error handling."""
    try:
        return subprocess.run(
            ["git"] + list(args),
            capture_output=True,
            text=True,
            check=check,
        )
    except subprocess.CalledProcessError as e:
        raise GitOperationError(args, e.stderr) from e


@contextmanager
def ensure_clean_checkout():
    """Ensure we return to original git branch after operations."""
    try:
        result = safe_git_command("rev-parse", "--abbrev-ref", "HEAD")
        original_branch = result.stdout.strip()
    except GitOperationError:
        original_branch = None

    try:
        yield
    finally:
        if original_branch:
            safe_git_command("checkout", original_branch, check=False)


def load_metadata_schema() -> dict:
    if not METADATA_SCHEMA_FILE.exists():
        raise FileNotFoundError(f"Metadata schema file not found: {METADATA_SCHEMA_FILE}")
    with METADATA_SCHEMA_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_metadata(metadata: dict) -> None:
    schema = load_metadata_schema()
    validate(instance=metadata, schema=schema)


def render_metadata(metadata: dict) -> str:
    return template.render(metadata=metadata)


def write_metadata(metadata: dict) -> None:
    rendered = render_metadata(metadata)
    validate_metadata(metadata)
    METADATA_FILE.write_text(rendered, encoding="utf-8")


def check_package_update(name: str, package_metadata: dict) -> dict | None:
    """Check a single package for updates."""
    current_version = package_metadata.get("version")
    repo_url = package_metadata.get("repo_url")

    if not current_version or not repo_url:
        return None

    owner, repo = get_owner_and_repo(repo_url)
    if not owner or not repo:
        return None

    try:
        latest_tag = get_latest_github_release_version(owner, repo)
    except Exception:
        return None

    if not latest_tag:
        return None

    match = re.search(r"v?(\d+\.\d+\.\d+)", latest_tag)
    if not match:
        return None

    latest_version = match.group(1)

    try:
        if semver.Version.parse(current_version) < semver.Version.parse(latest_version):
            return {
                "package": name,
                "from_version": current_version,
                "to_version": latest_version,
            }
    except ValueError:
        return None

    return None


def get_owner_and_repo(url: str):
    if url.startswith("git@"):
        try:
            path = url.split(":", 1)[1]
            if path.endswith(".git"):
                path = path[:-4]
            owner, repo = path.split("/", 1)
            return owner, repo
        except Exception:
            return None, None
    try:
        parsed = urlparse(url)
        path = parsed.path.lstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        owner, repo = path.split("/", 1)
        return owner, repo
    except Exception:
        return None, None


@tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
    retry=tenacity.retry_if_exception_type((requests.exceptions.Timeout, GitHubRateLimitError)),
)
def get_latest_github_release_version(owner: str, repo: str) -> str | None:
    """Get latest GitHub release version with retry logic."""
    if not owner or not repo:
        return None

    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(url, headers=headers, timeout=10)
    except requests.exceptions.Timeout:
        raise  # Will trigger retry

    if response.status_code == 403:
        # Rate limited
        remaining = int(response.headers.get("X-RateLimit-Remaining", 0))
        if remaining == 0:
            reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
            wait_time = max(2, reset_time - time.time())
            raise GitHubRateLimitError(
                f"Rate limited. Resets in {wait_time} seconds. Set GITHUB_TOKEN for higher limits."
            )
        return None

    if response.status_code == 429:
        raise GitHubRateLimitError("Too many requests")

    if response.status_code != 200:
        return None

    data = response.json()
    return data.get("tag_name")


def detect_updates(metadata: dict) -> list[dict]:
    """Detect available package updates with progress tracking."""
    console = Console()
    updates = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[green]Checking for updates...", total=len(metadata))

        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_package = {
                executor.submit(check_package_update, name, meta): name
                for name, meta in metadata.items()
            }

            for future in as_completed(future_to_package):
                package_name = future_to_package[future]
                try:
                    result = future.result(timeout=60)  # 60s timeout per package
                    if result:
                        updates.append(result)
                        console.print(
                            f"  [green]✓[/green] {result['package']}: "
                            f"{result['from_version']} → {result['to_version']}"
                        )
                except Exception:
                    console.print(f"  [red]✗[/red] {package_name}: Failed to check")
                finally:
                    progress.update(task, advance=1)

    return updates


@task(aliases=["a", "all"])
def update_all(c, dry_run: bool = False) -> None:
    metadata = metadata_cache.get()
    updates = detect_updates(metadata)

    if not updates:
        return

    if dry_run:
        return

    for update in updates:
        metadata[update["package"]]["version"] = update["to_version"]

    write_metadata(metadata)
    metadata_cache.clear()


@task(aliases=["p"])
def package(c, name: str, dry_run: bool = False) -> None:
    metadata = metadata_cache.get()

    if name not in metadata:
        return

    single = {name: metadata[name]}
    updates = detect_updates(single)

    if not updates:
        return

    if dry_run:
        return

    metadata[name]["version"] = updates[0]["to_version"]
    write_metadata(metadata)
    metadata_cache.clear()


@task
def add(
    c,
    repo_url: str,
    download_url: str,
    license: str,
    description: str,
    name: str | None = None,
    dry_run: bool = False,
) -> None:
    metadata = metadata_cache.get()

    owner, repo = get_owner_and_repo(repo_url)
    if not owner or not repo:
        raise ValueError("Unable to determine owner/repo from repo_url")

    inferred_name = repo.lower()
    package_name = name or inferred_name

    if package_name in metadata:
        raise ValueError(f"Package '{package_name}' already exists")

    latest_tag = get_latest_github_release_version(owner, repo)
    if not latest_tag:
        raise ValueError("Unable to determine latest release version")

    match = re.search(r"v?(\d+\.\d+\.\d+)", latest_tag)
    if not match:
        raise ValueError(f"Unable to extract semver from tag '{latest_tag}'")

    version = match.group(1)

    metadata[package_name] = {
        "description": description,
        "download_url": download_url,
        "repo_url": repo_url,
        "license": license,
        "version": version,
    }

    metadata = dict(sorted(metadata.items(), key=lambda item: item[0]))

    if dry_run:
        return

    write_metadata(metadata)
    metadata_cache.clear()


@task
def automation(c, ci: bool = False, dry_run: bool = False) -> None:
    """
    Run full update automation:
    - Run update.update-all
    - Create branch
    - Commit metadata
    - Create PR
    - Enable auto-merge (CI only)
    """

    metadata = metadata_cache.get()
    updates = detect_updates(metadata)

    if not updates:
        print("No updates found.")
        return

    branch_name = f"automation/update-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"

    if dry_run:
        print("Dry run mode enabled.")
        print(f"Would create branch: {branch_name}")
        print("Would commit: chore: update packages")
        print(f"Would create PR targeting 'main' with {len(updates)} update(s).")
        return

    with ensure_clean_checkout():
        for update in updates:
            metadata[update["package"]]["version"] = update["to_version"]

        write_metadata(metadata)
        metadata_cache.clear()

        # Checkout existing branch or create a new one
        branch_exists = safe_git_command("branch", "--list", branch_name).stdout.strip()

        if branch_exists:
            safe_git_command("checkout", branch_name)
        else:
            safe_git_command("checkout", "-b", branch_name)

        safe_git_command("add", str(METADATA_FILE))
        safe_git_command("commit", "-m", "chore: update packages")
        safe_git_command("push", "-u", "origin", branch_name)

        count = len(updates)

        if count <= 3:
            parts = [f"{u['package']} ({u['from_version']} → {u['to_version']})" for u in updates]
            title = f"chore: update {', '.join(parts)}"
        else:
            first = ", ".join(u["package"] for u in updates[:3])
            title = f"chore: update {first} +{count - 3} more"

        pretty_json = json.dumps(updates, indent=2)

        body = (
            "Automated weekly package updates.\n\n"
            f"{count} package(s) updated.\n\n"
            "<details>\n"
            "<summary>Updated Packages (click to expand)</summary>\n\n"
            "```json\n"
            f"{pretty_json}\n"
            "```\n\n"
            "</details>"
        )

        # Check for existing open PR
        pr_check = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--head",
                branch_name,
                "--state",
                "open",
                "--json",
                "number,url",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        existing_prs = json.loads(pr_check.stdout) if pr_check.stdout.strip() else []

        if existing_prs:
            pr_number = str(existing_prs[0]["number"])
            print(f"Reusing existing PR: {existing_prs[0]['url']}")
        else:
            subprocess.run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--title",
                    title,
                    "--body",
                    body,
                    "--head",
                    branch_name,
                    "--base",
                    "main",
                ],
                check=True,
            )
            pr_number = subprocess.check_output(
                ["gh", "pr", "view", "--json", "number", "--jq", ".number"],
                text=True,
            ).strip()

        # Add dependencies label (ignore failure if label does not exist)
        subprocess.run(
            ["gh", "pr", "edit", pr_number, "--add-label", "dependencies"],
            check=False,
        )

        # Enable auto-merge (respects branch protection rules)
        subprocess.run(
            ["gh", "pr", "merge", pr_number, "--auto", "--squash"],
            check=False,
        )
