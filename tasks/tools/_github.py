import os
import time
from urllib.parse import urlparse

import requests
import requests.exceptions
import tenacity

from tasks.tools._automation import GitHubRateLimitError


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
def get_latest_github_release_version(owner: str, repo: str) -> tuple[str | None, str | None, int]:
    """Get latest GitHub release version, published_at, and asset count with retry logic.

    Returns:
        (tag_name, published_at, asset_count) on success
        (None, None, 0) on failure
    """
    if not owner or not repo:
        return None, None, 0

    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
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
                f"Rate limited. Resets in {wait_time} seconds."
                " Set GITHUB_TOKEN or GH_TOKEN for higher limits."
            )
        return None, None, 0

    if response.status_code == 429:
        raise GitHubRateLimitError("Too many requests")

    if response.status_code != 200:
        return None, None, 0

    data = response.json()
    return data.get("tag_name"), data.get("published_at"), len(data.get("assets", []))


@tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
    retry=tenacity.retry_if_exception_type((requests.exceptions.Timeout, GitHubRateLimitError)),
)
def get_previous_github_releases(
    owner: str, repo: str, limit: int = 10
) -> list[tuple[str, str | None, int]]:
    """Get previous GitHub releases via GitHub REST API, ordered newest first.

    Each entry is (tag_name, published_at, asset_count).
    """
    if not owner or not repo:
        return []

    url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page={limit}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(url, headers=headers, timeout=10)
    except requests.exceptions.Timeout:
        raise  # Will trigger retry

    if response.status_code == 403:
        remaining = int(response.headers.get("X-RateLimit-Remaining", 0))
        if remaining == 0:
            reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
            wait_time = max(2, reset_time - time.time())
            raise GitHubRateLimitError(
                f"Rate limited. Resets in {wait_time} seconds."
                " Set GITHUB_TOKEN or GH_TOKEN for higher limits."
            )
        return []

    if response.status_code == 429:
        raise GitHubRateLimitError("Too many requests")

    if response.status_code != 200:
        return []

    data = response.json()

    releases: list[tuple[str, str | None, int]] = []
    for release in data:
        if release.get("draft", False) or release.get("prerelease", False):
            continue
        releases.append(
            (
                release.get("tag_name", ""),
                release.get("published_at"),
                len(release.get("assets", [])),
            )
        )
    return releases
