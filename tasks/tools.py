from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlparse

from dotenv import load_dotenv
from invoke.context import Context
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

from tasks.lib import (
    METADATA_FILE,
    METADATA_SCHEMA_FILE,
    ROOT_DIR,
    MetadataCache,
    PackageDownloader,
    fetch_asset_digest,
    render_download_url_for_linux_amd64,
    render_template,
)

# Minimum age in days before a release can be used for updates
RELEASE_AGE_DAYS = 7

metadata_cache = MetadataCache()

load_dotenv()


def _format_checked_versions(checked_versions: list[dict]) -> str:
    """Format checked_versions list into a display string."""
    if not checked_versions:
        return ""
    parts = []
    for entry in checked_versions:
        parts.append(f"v{entry['version']} ({entry['age_days']}d)")
    return ", ".join(parts)


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


def _try_previous_release(
    name: str, owner: str, repo: str, current_version: str, *, cooldown: int = RELEASE_AGE_DAYS
) -> tuple[dict | None, list[dict]]:
    """Walk back through previous releases to find one old enough to use.

    Returns a tuple of (result_dict_or_None, checked_versions_list).
    checked_versions contains entries for each release that reached age computation.
    """
    checked_versions: list[dict] = []

    try:
        releases = get_previous_github_releases(owner, repo)
    except Exception:
        return None, []

    if not releases:
        return None, []

    try:
        current_semver = semver.Version.parse(current_version)
    except ValueError:
        return None, []

    for tag, published_at in releases:
        match = re.search(r"v?(\d+\.\d+\.\d+)", tag)
        if not match:
            continue
        release_version = match.group(1)
        try:
            release_semver = semver.Version.parse(release_version)
        except ValueError:
            continue
        if release_semver <= current_semver:
            continue
        if not published_at:
            continue
        try:
            published_date = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            age_days = (datetime.now(UTC) - published_date).days
        except (ValueError, TypeError):
            continue
        if age_days >= cooldown:
            checked_versions.append(
                {"version": release_version, "age_days": age_days, "status": "selected"}
            )
            return {
                "package": name,
                "from_version": current_version,
                "to_version": release_version,
            }, checked_versions
        checked_versions.append(
            {"version": release_version, "age_days": age_days, "status": "too_young"}
        )
    return None, checked_versions


def check_package_update(
    name: str, package_metadata: dict, *, cooldown: int = RELEASE_AGE_DAYS
) -> dict | None:
    """Check a single package for updates.

    Returns:
        - dict with update info if newer version available
        - dict with skip info if release is too young
        - None if no update available or error
    """
    current_version = package_metadata.get("version")
    repo_url = package_metadata.get("repo_url")
    if not current_version or not repo_url:
        return None
    owner, repo = get_owner_and_repo(repo_url)
    if not owner or not repo:
        return None
    try:
        latest_tag, published_at = get_latest_github_release_version(owner, repo)
    except Exception:
        return None
    if not latest_tag:
        return None
    if published_at and cooldown > 0:
        try:
            published_date = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            age_days = (datetime.now(UTC) - published_date).days
            if age_days < cooldown:
                skipped_version = latest_tag.lstrip("v")
                if skipped_version == current_version:
                    return None
                fallback, fallback_checked = _try_previous_release(
                    name, owner, repo, current_version, cooldown=cooldown
                )
                latest_entry = {
                    "version": skipped_version,
                    "age_days": age_days,
                    "status": "too_young",
                }
                deduped = [e for e in fallback_checked if e["version"] != skipped_version]
                if fallback:
                    fallback["checked_versions"] = [latest_entry] + deduped
                    return fallback
                return {
                    "package": name,
                    "current_version": current_version,
                    "skipped_version": skipped_version,
                    "reason": f"Release too young ({age_days} days old, < {cooldown} days)",
                    "checked_versions": [latest_entry] + deduped,
                }
        except (ValueError, TypeError):
            pass
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
def get_latest_github_release_version(owner: str, repo: str) -> tuple[str | None, str | None]:
    """Get latest GitHub release version and published_at with retry logic.

    Returns:
        (tag_name, published_at) on success
        (None, None) on failure
    """
    if not owner or not repo:
        return None, None

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
        return None, None

    if response.status_code == 429:
        raise GitHubRateLimitError("Too many requests")

    if response.status_code != 200:
        return None, None

    data = response.json()
    return data.get("tag_name"), data.get("published_at")


def get_previous_github_releases(
    owner: str, repo: str, limit: int = 10
) -> list[tuple[str, str | None]]:
    """Get previous GitHub releases via gh CLI, ordered newest first."""
    if not owner or not repo:
        return []

    full_repo = f"{owner}/{repo}"
    result = subprocess.run(
        [
            "gh",
            "release",
            "list",
            "--repo",
            full_repo,
            "--limit",
            str(limit),
            "--json",
            "tagName,publishedAt,isDraft,isPrerelease",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return []

    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return []

    releases: list[tuple[str, str | None]] = []
    for release in data:
        if release.get("isDraft", False) or release.get("isPrerelease", False):
            continue
        releases.append((release.get("tagName", ""), release.get("publishedAt")))
    return releases


def detect_updates(
    metadata: dict, *, cooldown: int = RELEASE_AGE_DAYS
) -> tuple[list[dict], list[dict]]:
    """Detect available package updates with progress tracking.

    Returns:
        tuple of (updates, skipped) where:
        - updates: list of dicts with 'package', 'from_version', 'to_version'
        - skipped: list of dicts with 'package', 'current_version', 'skipped_version', 'reason'
    """
    console = Console()
    updates = []
    skipped = []

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
                executor.submit(check_package_update, name, meta, cooldown=cooldown): name
                for name, meta in metadata.items()
            }

            for future in as_completed(future_to_package):
                package_name = future_to_package[future]
                try:
                    result = future.result(timeout=60)  # 60s timeout per package
                    if result:
                        if "skipped_version" in result:
                            skipped.append(result)
                        else:
                            updates.append(result)
                            console.print(
                                f"  [green]✓[/green] {result['package']}: "
                                f"{result['from_version']} → {result['to_version']}"
                            )
                            if "checked_versions" in result:
                                chain = _format_checked_versions(result["checked_versions"])
                                console.print(f"    walked: {chain}")
                except Exception:
                    console.print(f"  [red]✗[/red] {package_name}: Failed to check")
                finally:
                    progress.update(task, advance=1)

    return updates, skipped


def check_required_tools(download_url: str) -> None:
    """Check for required command line tools."""
    required = {"curl"}

    if download_url.endswith(".zip"):
        required.add("unzip")
    elif download_url.endswith((".tar", ".tar.gz", ".tar.bz2", ".tar.xz")):
        required.add("tar")
    elif download_url.endswith((".gz", ".bz2")):
        required.add("gunzip")

    for tool in required:
        if not shutil.which(tool):
            raise RuntimeError(f"Required tool '{tool}' not found in PATH")


def resolve_install_path(local: bool = False, dist: bool = True) -> Path:
    """Resolve install path based on flags."""
    if local:
        home = Path.home()
        local_bin = home / ".local" / "bin"
        fallback_bin = home / "bin"

        path_entries = [p for p in os.getenv("PATH", "").split(os.pathsep) if p]
        normalized_path_entries = {str(Path(p).resolve()) for p in path_entries}

        if local_bin.exists() and str(local_bin.resolve()) in normalized_path_entries:
            return local_bin
        else:
            return fallback_bin

    if dist:
        return ROOT_DIR / "dist"

    raise ValueError("Either --local or --dist must be specified")


def install_single_package(
    c: Context,
    name: str,
    install_path: Path,
    force: bool = False,
) -> None:
    """Install a single tool."""
    metadata = metadata_cache.get()

    if name not in metadata:
        raise ValueError(f"Tool '{name}' not found in metadata")

    package_metadata = metadata[name]
    download_url = render_template(name, package_metadata, package_metadata["download_url"])

    check_required_tools(download_url)

    if force and (install_path / name).exists():
        c.run(f"rm -rvf {install_path}/{name}")

    if (install_path / name).exists():
        print(f"{name} already installed at {install_path}")
    else:
        if not install_path.exists():
            install_path.mkdir(parents=True, exist_ok=True)

        downloader = PackageDownloader(
            c,
            package_name=name,
            download_url=download_url,
            install_path=str(install_path),
            package_exe=package_metadata.get("package_exe", None),
            binary=package_metadata.get("binary", False),
            sha256=package_metadata.get("sha256"),
        )

        downloader.download()


@task
def update(
    c,
    name: str = "",
    pr: bool = False,
    dry_run: bool = False,
    cooldown: int = RELEASE_AGE_DAYS,
) -> None:
    """Check and update tools. Use --name for single tool, --pr for PR automation."""
    console = Console()
    metadata = metadata_cache.get()

    if name:
        if name not in metadata:
            return
        check_data = {name: metadata[name]}
    else:
        check_data = metadata

    updates, skipped = detect_updates(check_data, cooldown=cooldown)

    if pr:
        if not updates and not skipped:
            console.print("No updates found.")
            return

        if not updates:
            console.print("No updates found, but some releases were skipped:")
            for s in skipped:
                chain_str = ""
                if "checked_versions" in s:
                    chain_str = f" (walked: {_format_checked_versions(s['checked_versions'])})"
                console.print(
                    f"  [yellow]⏭[/yellow] {s['package']}: {s['current_version']} → "
                    f"{s['skipped_version']} ({s['reason']}){chain_str}"
                )
            return

        branch_name = f"automation/update-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"

        if dry_run:
            console.print("[bold]Dry run mode enabled.[/bold]")
            console.print(f"Would create branch: [cyan]{branch_name}[/cyan]")
            console.print("Would commit: [cyan]chore: update tools[/cyan]")
            console.print(
                f"Would create PR targeting [cyan]'main'[/cyan] with {len(updates)} update(s)."
            )
            return

        with ensure_clean_checkout():
            for u in updates:
                metadata[u["package"]]["version"] = u["to_version"]

            write_metadata(metadata)
            metadata_cache.clear()

            # Checkout existing branch or create a new one
            branch_exists = safe_git_command("branch", "--list", branch_name).stdout.strip()

            if branch_exists:
                safe_git_command("checkout", branch_name)
            else:
                safe_git_command("checkout", "-b", branch_name)

            safe_git_command("add", str(METADATA_FILE))
            safe_git_command("commit", "-m", "chore: update tools")
            safe_git_command("push", "-u", "origin", branch_name)

            count = len(updates)

            if count <= 3:
                parts = [
                    f"{u['package']} ({u['from_version']} → {u['to_version']})" for u in updates
                ]
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

            if skipped:
                skip_lines = [
                    "| Package | Current | Skipped | Reason | Checked Versions |",
                    "|---|---|---|---|---|",
                ]
                for s in skipped:
                    chain = _format_checked_versions(s.get("checked_versions", []))
                    skip_lines.append(
                        f"| {s['package']} | {s['current_version']} "
                        f"| {s['skipped_version']} | {s['reason']} | {chain} |"
                    )
                skip_table = "\n".join(skip_lines)
                body += (
                    "\n\n<details>\n"
                    "<summary>Skipped Releases (click to expand)</summary>\n\n"
                    f"{skip_table}\n\n"
                    "</details>"
                )

            # Check for existing open PR
            try:
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
            except subprocess.CalledProcessError as e:
                raise AutomationError(
                    f"Failed to check for existing PRs: {e.stderr.strip()}"
                ) from e

            existing_prs = json.loads(pr_check.stdout) if pr_check.stdout.strip() else []

            if existing_prs:
                pr_number = str(existing_prs[0]["number"])
                console.print(f"Reusing existing PR: [cyan]{existing_prs[0]['url']}[/cyan]")
            else:
                # Write body to temp file to avoid CLI argument length limits
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".md", delete=False, encoding="utf-8"
                ) as body_file:
                    body_file.write(body)
                    body_path = body_file.name

                try:
                    pr_create = subprocess.run(
                        [
                            "gh",
                            "pr",
                            "create",
                            "--title",
                            title,
                            "--body-file",
                            body_path,
                            "--head",
                            branch_name,
                            "--base",
                            "main",
                        ],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                except subprocess.CalledProcessError as e:
                    raise AutomationError(f"Failed to create PR: {e.stderr.strip()}") from e
                finally:
                    Path(body_path).unlink(missing_ok=True)
                pr_url = pr_create.stdout.strip()
                pr_number = pr_url.rstrip("/").rsplit("/", 1)[-1]
                console.print(f"Created PR: [cyan]{pr_url}[/cyan]")

            label_result = subprocess.run(
                ["gh", "pr", "edit", pr_number, "--add-label", "dependencies"],
                capture_output=True,
                text=True,
                check=False,
            )
            if label_result.returncode != 0:
                console.print(
                    f"  [yellow]⚠[/yellow] Failed to add label: {label_result.stderr.strip()}"
                )

            merge_result = subprocess.run(
                ["gh", "pr", "merge", pr_number, "--auto", "--squash", "--delete-branch"],
                capture_output=True,
                text=True,
                check=False,
            )
            if merge_result.returncode != 0:
                msg = merge_result.stderr.strip()
                console.print(f"  [yellow]⚠[/yellow] Failed to enable auto-merge: {msg}")
    else:
        if not updates:
            return

        if dry_run:
            return

        for u in updates:
            metadata[u["package"]]["version"] = u["to_version"]

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
    """Add new package to metadata."""
    metadata = metadata_cache.get()

    owner, repo = get_owner_and_repo(repo_url)
    if not owner or not repo:
        raise ValueError("Unable to determine owner/repo from repo_url")

    inferred_name = repo.lower()
    package_name = name or inferred_name

    if package_name in metadata:
        raise ValueError(f"Package '{package_name}' already exists")

    latest_tag, _ = get_latest_github_release_version(owner, repo)
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
def install(
    c: Context,
    name: str = "",
    local: bool = False,
    dist: bool = True,
    force: bool = False,
) -> None:
    """Install tools to dist or local."""
    install_path = resolve_install_path(local=local, dist=dist)

    if name:
        install_single_package(c, name, install_path, force=force)
    else:
        metadata = metadata_cache.get()
        for package_id in metadata:
            install_single_package(c, package_id, install_path, force=force)
        metadata_cache.clear()


@task
def digests(
    c,
    name: str = "",
) -> None:
    """Fetch SHA256 digests for all tools and write to metadata.yaml."""
    console = Console()
    metadata = metadata_cache.get()

    if name:
        if name not in metadata:
            console.print(f"[red]Tool '{name}' not found in metadata[/red]")
            return
        tools_to_process = {name: metadata[name]}
    else:
        tools_to_process = metadata

    updated = False

    for tool_name, pkg_meta in tools_to_process.items():
        version = pkg_meta.get("version")
        repo_url = pkg_meta.get("repo_url")

        if not version or not repo_url:
            console.print(f"  [yellow]SKIP[/yellow] {tool_name}: missing version or repo_url")
            continue

        if tool_name == "asdf":
            console.print(
                f"  [yellow]SKIP[/yellow] {tool_name}: only MD5 digests available, not SHA256"
            )
            continue

        owner, repo = get_owner_and_repo(repo_url)
        if not owner or not repo:
            console.print(f"  [yellow]SKIP[/yellow] {tool_name}: cannot parse owner/repo")
            continue

        resolved_url = render_download_url_for_linux_amd64(tool_name, pkg_meta)
        asset_filename = resolved_url.rsplit("/", 1)[-1] if "/" in resolved_url else resolved_url

        sha256 = fetch_asset_digest(
            owner=owner,
            repo=repo,
            version=version,
            asset_filename=asset_filename,
            tool_name=tool_name,
            package_metadata=pkg_meta,
        )

        if sha256:
            pkg_meta["sha256"] = sha256
            updated = True
            console.print(f"  [green]OK[/green] {tool_name}: {sha256[:16]}...")
        else:
            console.print(f"  [red]MISSING[/red] {tool_name}: digest not found")

    if updated:
        write_metadata(metadata)
        metadata_cache.clear()
        console.print("\n[bold green]Metadata updated with sha256 digests.[/bold green]")
    else:
        console.print("\n[yellow]No digests found.[/yellow]")
