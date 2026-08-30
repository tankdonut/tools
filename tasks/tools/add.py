from invoke.tasks import task

from tasks.lib import extract_version_from_tag
from tasks.tools._github import get_latest_github_release_version, get_owner_and_repo
from tasks.tools._metadata import metadata_cache, write_metadata


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

    latest_tag, _, _ = get_latest_github_release_version(owner, repo)
    if not latest_tag:
        raise ValueError("Unable to determine latest release version")

    version = extract_version_from_tag(latest_tag)
    if not version:
        raise ValueError(f"Unable to extract version from tag '{latest_tag}'")

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
