from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import logging

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

from tasks.lib import (
    extract_semver_from_tag,
    fetch_asset_digest,
    render_download_url_for_linux_amd64,
)
from tasks.tools._github import (
    get_latest_github_release_version,
    get_owner_and_repo,
    get_previous_github_releases,
)

logger = logging.getLogger(__name__)

# Minimum age in days before a release can be used for updates
RELEASE_AGE_DAYS = 7


def _format_checked_versions(checked_versions: list[dict]) -> str:
    """Format checked_versions list into a display string."""
    if not checked_versions:
        return ""
    parts = []
    for entry in checked_versions:
        parts.append(f"v{entry['version']} ({entry['age_days']}d)")
    return ", ".join(parts)


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
    except Exception as e:
        logger.warning("Failed to fetch previous releases for %s/%s: %s", owner, repo, e)
        return None, []

    if not releases:
        return None, []

    try:
        current_semver = semver.Version.parse(current_version)
    except ValueError:
        return None, []

    for tag, published_at, asset_count in releases:
        if asset_count == 0:
            continue
        release_version = extract_semver_from_tag(tag)
        if not release_version:
            continue
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
        latest_tag, published_at, asset_count = get_latest_github_release_version(owner, repo)
    except Exception as e:
        logger.warning("Failed to check update for %s: %s", name, e)
        return None
    if not latest_tag:
        return None
    if asset_count == 0:
        fallback, fallback_checked = _try_previous_release(
            name, owner, repo, current_version, cooldown=cooldown
        )
        skipped_version = extract_semver_from_tag(latest_tag)
        if not skipped_version:
            return None
        try:
            if semver.Version.parse(skipped_version) == semver.Version.parse(current_version):
                return None
        except ValueError:
            pass
        latest_entry = {
            "version": skipped_version,
            "age_days": 0,
            "status": "no_assets",
        }
        deduped = [e for e in fallback_checked if e["version"] != skipped_version]
        if fallback:
            fallback["checked_versions"] = [latest_entry] + deduped
            return fallback
        return {
            "package": name,
            "current_version": current_version,
            "skipped_version": skipped_version,
            "reason": f"Release has no assets (v{skipped_version})",
            "checked_versions": [latest_entry] + deduped,
        }
    if published_at and cooldown > 0:
        try:
            published_date = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            age_days = (datetime.now(UTC) - published_date).days
            if age_days < cooldown:
                skipped_version = extract_semver_from_tag(latest_tag)
                if not skipped_version:
                    return None
                try:
                    skipped_sv = semver.Version.parse(skipped_version)
                    current_sv = semver.Version.parse(current_version)
                    if skipped_sv == current_sv:
                        return None
                except ValueError:
                    pass
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
    latest_version = extract_semver_from_tag(latest_tag)
    if not latest_version:
        return None
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
                except Exception:
                    console.print(f"  [red]✗[/red] {package_name}: Failed to check")
                finally:
                    progress.update(task, advance=1)

    return updates, skipped


def _update_sha256_for_updates(metadata: dict, updates: list[dict]) -> dict[str, str | None]:
    """Fetch and set SHA256 digests for updated packages.

    Returns a mapping of package name to SHA256 digest (or None if not found).
    """
    sha_map: dict[str, str | None] = {}

    for u in updates:
        pkg_name = u["package"]
        pkg_meta = metadata[pkg_name]
        version = pkg_meta.get("version")
        repo_url = pkg_meta.get("repo_url")

        if not version or not repo_url:
            sha_map[pkg_name] = None
            continue

        if pkg_name == "asdf":
            sha_map[pkg_name] = None
            continue

        owner, repo = get_owner_and_repo(repo_url)
        if not owner or not repo:
            sha_map[pkg_name] = None
            continue

        resolved_url = render_download_url_for_linux_amd64(pkg_name, pkg_meta)
        asset_filename = resolved_url.rsplit("/", 1)[-1] if "/" in resolved_url else resolved_url

        sha256 = fetch_asset_digest(
            owner=owner,
            repo=repo,
            version=version,
            asset_filename=asset_filename,
            tool_name=pkg_name,
            package_metadata=pkg_meta,
        )

        if sha256:
            pkg_meta["sha256"] = sha256
        sha_map[pkg_name] = sha256

    return sha_map
