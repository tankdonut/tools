from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from tasks.lib import compare_versions, extract_semver_from_tag, extract_version_from_tag
from tasks.tools._github import (
    GitHubRateLimitError,
    get_latest_github_release_version,
    get_owner_and_repo,
    get_previous_github_releases,
)
from tasks.tools._updates import detect_updates


class TestDetectUpdates:
    """Test detect_updates function."""

    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_detect_updates_found(self, mock_latest, sample_metadata):
        """Test detecting updates when newer versions exist."""
        mock_latest.side_effect = [("v2.1.0", None, 1), ("v3.0.0", None, 1)]
        updates, _skipped = detect_updates(sample_metadata)

        assert len(updates) == 2
        assert updates[0]["package"] == "test-pkg1"
        assert updates[0]["from_version"] == "1.0.0"
        assert updates[0]["to_version"] == "2.1.0"

    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_detect_updates_none_found(self, mock_latest, sample_metadata):
        """Test when no updates are available."""
        mock_latest.side_effect = [("v1.0.0", None, 1), ("v2.0.0", None, 1)]
        updates, _skipped = detect_updates(sample_metadata)

        assert len(updates) == 0

    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_detect_updates_invalid_version(self, mock_latest, sample_metadata):
        """Test handling of invalid version tags."""
        mock_latest.side_effect = [("invalid-tag", None, 1), ("v3.0.0", None, 1)]
        updates, _skipped = detect_updates(sample_metadata)

        assert len(updates) == 1


class TestGetOwnerAndRepo:
    """Test get_owner_and_repo function."""

    def test_https_url(self):
        """Test parsing HTTPS GitHub URLs."""
        owner, repo = get_owner_and_repo("https://github.com/test/repo")
        assert owner == "test"
        assert repo == "repo"

    def test_ssh_url(self):
        """Test parsing SSH GitHub URLs."""
        owner, repo = get_owner_and_repo("git@github.com:test/repo.git")
        assert owner == "test"
        assert repo == "repo"

    def test_ssh_url_without_git_suffix(self):
        """Test parsing SSH URL without .git suffix."""
        owner, repo = get_owner_and_repo("git@github.com:test/repo")
        assert owner == "test"
        assert repo == "repo"

    def test_invalid_url(self):
        """Test handling of invalid URLs."""
        owner, repo = get_owner_and_repo("not-a-valid-url")
        assert owner is None
        assert repo is None


class TestGetLatestGitHubReleaseVersion:
    """Test get_latest_github_release_version function."""

    @patch("tasks.tools._github.requests.get")
    def test_success(self, mock_get):
        """Test successful API call."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v1.2.3",
            "published_at": None,
            "assets": [{"name": "binary"}],
        }
        mock_get.return_value = mock_response

        version = get_latest_github_release_version("test", "repo")
        assert version == ("v1.2.3", None, 1)

    @patch("tasks.tools._github.requests.get")
    def test_with_auth_token(self, mock_get, monkeypatch):
        """Test API call with authentication token."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v1.2.3",
            "published_at": None,
            "assets": [{"name": "binary"}],
        }
        mock_get.return_value = mock_response

        get_latest_github_release_version("test", "repo")

        call_args = mock_get.call_args
        assert "Authorization" in call_args.kwargs["headers"]
        assert call_args.kwargs["headers"]["Authorization"] == "Bearer test-token"

    @patch("tasks.tools._github.requests.get")
    def test_with_gh_token_fallback(self, mock_get, monkeypatch):
        """Test API call falls back to GH_TOKEN when GITHUB_TOKEN is not set."""
        monkeypatch.setenv("GH_TOKEN", "gh-test-token")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v1.2.3",
            "published_at": None,
            "assets": [{"name": "binary"}],
        }
        mock_get.return_value = mock_response

        get_latest_github_release_version("test", "repo")

        call_args = mock_get.call_args
        assert "Authorization" in call_args.kwargs["headers"]
        assert call_args.kwargs["headers"]["Authorization"] == "Bearer gh-test-token"

    @patch("tasks.tools._github.requests.get")
    def test_failure_status_code(self, mock_get):
        """Test handling of non-200 status codes."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        version = get_latest_github_release_version("test", "repo")
        assert version == (None, None, 0)

    @patch("tasks.tools._github.requests.get")
    def test_no_assets_returns_zero(self, mock_get):
        """Test that release with no assets returns asset_count=0."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v2.0.0",
            "published_at": "2025-01-01T00:00:00Z",
            "assets": [],
        }
        mock_get.return_value = mock_response

        version = get_latest_github_release_version("test", "repo")
        assert version == ("v2.0.0", "2025-01-01T00:00:00Z", 0)


class TestAutomationDryRun:
    """Test automation task dry-run mode."""

    @patch("tasks.tools.update.subprocess.run")
    @patch("tasks.tools.update.metadata_cache")
    @patch("tasks.tools.update.detect_updates")
    @patch("pathlib.Path.read_bytes")
    @patch("pathlib.Path.exists")
    def test_automation_dry_run_side_effects(
        self,
        mock_exists,
        mock_read_bytes,
        mock_detect,
        mock_cache,
        mock_subprocess,
        temp_metadata_file,
    ):
        """Test that dry-run mode has no side effects."""
        from invoke.context import Context
        from tasks.tools import update

        mock_exists.return_value = True
        mock_read_bytes.return_value = b"test-content"

        updates_list = [{"package": "test-pkg", "from_version": "1.0.0", "to_version": "2.0.0"}]

        mock_cache.get.return_value = {"test-pkg": {"version": "1.0.0"}}
        mock_cache.clear = Mock()
        mock_detect.return_value = (updates_list, [])

        # Mock git commands
        def mock_run_side_effect(*args, **kwargs):
            if "rev-parse" in str(args):
                return Mock(stdout="main\n", stderr="", returncode=0)
            return Mock(stdout="", stderr="", returncode=0)

        mock_subprocess.side_effect = mock_run_side_effect

        # Run automation in dry-run mode with proper Context
        ctx = Context()
        update(ctx, pr=True, dry_run=True)

        # In dry-run mode, NO git operations should be called
        # The function returns early before any git commands
        git_calls = [str(git_call) for git_call in mock_subprocess.call_args_list]

        # Should NOT have called ANY git operations
        assert not any("git" in git_call for git_call in git_calls)

    @patch("tasks.tools.update.subprocess.run")
    @patch("tasks.tools.update.metadata_cache")
    @patch("tasks.tools.update.detect_updates")
    @patch("tasks.tools.update.write_metadata")
    @patch("tasks.tools.update.subprocess.check_output")
    def test_automation_dry_run_no_metadata_modification(
        self,
        mock_check_output,
        mock_write,
        mock_detect,
        mock_cache,
        mock_subprocess,
    ):
        """Test that dry-run does not write metadata."""
        from invoke.context import Context
        from tasks.tools import update

        mock_cache.get.return_value = {"test-pkg": {"version": "1.0.0"}}
        mock_cache.clear = Mock()
        mock_detect.return_value = (
            [{"package": "test-pkg", "from_version": "1.0.0", "to_version": "2.0.0"}],
            [],
        )

        def mock_run_side_effect(*args, **kwargs):
            if "rev-parse" in str(args):
                return Mock(stdout="main\n", stderr="", returncode=0)
            return Mock(stdout="", stderr="", returncode=0)

        mock_subprocess.side_effect = mock_run_side_effect
        mock_check_output.return_value = "1"

        # Run automation in dry-run mode with proper Context
        ctx = Context()
        update(ctx, pr=True, dry_run=True)

        # Verify write_metadata was not called
        mock_write.assert_not_called()


class TestReleaseAgeFilter:
    """Test release age filtering for updates."""

    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_release_6_days_old_is_skipped(self, mock_latest):
        """Test that releases younger than 7 days are skipped."""
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        # Mock a release published 6 days ago
        six_days_ago = datetime.now(UTC) - timedelta(days=6)
        published_at = six_days_ago.isoformat()
        mock_latest.return_value = ("v2.0.0", published_at, 1)

        # Current version is 1.0.0, latest is 2.0.0 but only 6 days old
        metadata = {"test-pkg": {"version": "1.0.0", "repo_url": "https://github.com/test/repo"}}

        result = check_package_update("test-pkg", metadata["test-pkg"])

        # Should return skip info because release is too young (< 7 days)
        assert result is not None
        assert "skipped_version" in result
        assert result["skipped_version"] == "2.0.0"
        assert result["package"] == "test-pkg"
        assert "too young" in result["reason"]

    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_release_exactly_7_days_old_is_not_skipped(self, mock_latest):
        """Test that releases exactly 7 days old are NOT skipped."""
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        # Mock a release published exactly 7 days ago
        seven_days_ago = datetime.now(UTC) - timedelta(days=7)
        published_at = seven_days_ago.isoformat()
        mock_latest.return_value = ("v2.0.0", published_at, 1)

        metadata = {"test-pkg": {"version": "1.0.0", "repo_url": "https://github.com/test/repo"}}

        result = check_package_update("test-pkg", metadata["test-pkg"])

        # Should NOT be skipped - 7 days is the threshold
        assert result is not None
        assert result["package"] == "test-pkg"
        assert result["from_version"] == "1.0.0"
        assert result["to_version"] == "2.0.0"

    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_release_8_days_old_is_not_skipped(self, mock_latest):
        """Test that releases older than 7 days are NOT skipped."""
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        # Mock a release published 8 days ago
        eight_days_ago = datetime.now(UTC) - timedelta(days=8)
        published_at = eight_days_ago.isoformat()
        mock_latest.return_value = ("v2.0.0", published_at, 1)

        metadata = {"test-pkg": {"version": "1.0.0", "repo_url": "https://github.com/test/repo"}}

        result = check_package_update("test-pkg", metadata["test-pkg"])

        # Should NOT be skipped - release is old enough
        assert result is not None
        assert result["package"] == "test-pkg"
        assert result["from_version"] == "1.0.0"
        assert result["to_version"] == "2.0.0"

    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_release_without_published_at_is_not_skipped(self, mock_latest):
        """Test that releases without published_at are NOT skipped (defensive)."""
        from tasks.tools._updates import check_package_update

        # Mock a release with no published_at (None)
        mock_latest.return_value = ("v2.0.0", None, 1)

        metadata = {"test-pkg": {"version": "1.0.0", "repo_url": "https://github.com/test/repo"}}

        result = check_package_update("test-pkg", metadata["test-pkg"])

        # Should NOT be skipped - defensive: if no date, allow update
        assert result is not None
        assert result["package"] == "test-pkg"
        assert result["from_version"] == "1.0.0"
        assert result["to_version"] == "2.0.0"


class TestGetPreviousGitHubReleases:
    """Test get_previous_github_releases function."""

    @patch("tasks.tools._github.requests.get")
    def test_success(self, mock_get):
        """Successful API call returns non-draft, non-prerelease releases."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "tag_name": "v2.0.0",
                "published_at": "2025-01-15T00:00:00Z",
                "draft": False,
                "prerelease": False,
                "assets": [{"name": "binary"}],
            },
            {
                "tag_name": "v1.9.0",
                "published_at": "2025-01-10T00:00:00Z",
                "draft": False,
                "prerelease": False,
                "assets": [{"name": "binary"}],
            },
            {
                "tag_name": "v1.8.0",
                "published_at": "2025-01-05T00:00:00Z",
                "draft": True,
                "prerelease": False,
                "assets": [{"name": "binary"}],
            },
            {
                "tag_name": "v1.7.0",
                "published_at": "2025-01-01T00:00:00Z",
                "draft": False,
                "prerelease": True,
                "assets": [{"name": "binary"}],
            },
        ]
        mock_get.return_value = mock_response

        result = get_previous_github_releases("test", "repo")

        assert len(result) == 2
        assert result[0] == ("v2.0.0", "2025-01-15T00:00:00Z", 1)
        assert result[1] == ("v1.9.0", "2025-01-10T00:00:00Z", 1)

    @patch("tasks.tools._github.requests.get")
    def test_empty_releases(self, mock_get):
        """Empty list from API returns empty list."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get.return_value = mock_response

        result = get_previous_github_releases("test", "repo")

        assert result == []

    @patch("tasks.tools._github.requests.get")
    def test_non_200_returns_empty(self, mock_get):
        """Non-200 status code returns empty list."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        result = get_previous_github_releases("test", "repo")

        assert result == []

    @patch("tasks.tools._github.requests.get")
    def test_invalid_json_raises_value_error(self, mock_get):
        """Response with invalid JSON raises ValueError (propagated from response.json())."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("bad json")
        mock_get.return_value = mock_response

        with pytest.raises(ValueError, match="bad json"):
            get_previous_github_releases("test", "repo")

    def test_empty_owner_returns_empty(self):
        """Empty owner returns empty list without making API call."""
        result = get_previous_github_releases("", "repo")
        assert result == []

    @patch("tasks.tools._github.requests.get")
    def test_rate_limit_403_raises(self, mock_get):
        """HTTP 403 with rate limit remaining=0 raises GitHubRateLimitError."""
        import tenacity

        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.headers = {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "9999999999",
        }
        mock_get.return_value = mock_response

        with pytest.raises(tenacity.RetryError) as exc_info:
            get_previous_github_releases("test", "repo")

        assert isinstance(exc_info.value.last_attempt.exception(), GitHubRateLimitError)

    @patch("tasks.tools._github.requests.get")
    def test_rate_limit_429_raises(self, mock_get):
        """HTTP 429 raises GitHubRateLimitError."""
        import tenacity

        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_get.return_value = mock_response

        with pytest.raises(tenacity.RetryError) as exc_info:
            get_previous_github_releases("test", "repo")

        assert isinstance(exc_info.value.last_attempt.exception(), GitHubRateLimitError)


class TestReleaseFallback:
    """Test fallback to previous releases when latest is too young."""

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_fallback_to_previous_release(self, mock_latest, mock_previous):
        """When latest is too young, fall back to the previous release if old enough."""
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        now = datetime.now(UTC)
        three_days_ago = (now - timedelta(days=3)).isoformat()
        ten_days_ago = (now - timedelta(days=10)).isoformat()

        mock_latest.return_value = ("v1.3.9", three_days_ago, 1)
        mock_previous.return_value = [
            ("v1.3.9", three_days_ago, 1),
            ("v1.3.8", ten_days_ago, 1),
        ]

        metadata = {"version": "1.3.5", "repo_url": "https://github.com/test/repo"}

        result = check_package_update("opencode", metadata)

        assert result is not None
        assert result["package"] == "opencode"
        assert result["from_version"] == "1.3.5"
        assert result["to_version"] == "1.3.8"

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_fallback_all_previous_too_young(self, mock_latest, mock_previous):
        """When all previous releases are also too young, return skip info."""
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        now = datetime.now(UTC)
        three_days_ago = (now - timedelta(days=3)).isoformat()
        five_days_ago = (now - timedelta(days=5)).isoformat()

        mock_latest.return_value = ("v1.3.9", three_days_ago, 1)
        mock_previous.return_value = [
            ("v1.3.9", three_days_ago, 1),
            ("v1.3.8", five_days_ago, 1),
        ]

        metadata = {"version": "1.3.5", "repo_url": "https://github.com/test/repo"}

        result = check_package_update("opencode", metadata)

        assert result is not None
        assert "skipped_version" in result
        assert result["skipped_version"] == "1.3.9"

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_fallback_previous_equal_to_current(self, mock_latest, mock_previous):
        """When previous release equals current version, return skip info."""
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        now = datetime.now(UTC)
        three_days_ago = (now - timedelta(days=3)).isoformat()
        ten_days_ago = (now - timedelta(days=10)).isoformat()

        mock_latest.return_value = ("v1.3.9", three_days_ago, 1)
        mock_previous.return_value = [
            ("v1.3.9", three_days_ago, 1),
            ("v1.3.5", ten_days_ago, 1),
        ]

        metadata = {"version": "1.3.5", "repo_url": "https://github.com/test/repo"}

        result = check_package_update("opencode", metadata)

        assert result is not None
        assert "skipped_version" in result

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_fallback_previous_older_than_current(self, mock_latest, mock_previous):
        """When all previous releases are older than current, return skip info."""
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        now = datetime.now(UTC)
        three_days_ago = (now - timedelta(days=3)).isoformat()
        ten_days_ago = (now - timedelta(days=10)).isoformat()

        mock_latest.return_value = ("v1.3.9", three_days_ago, 1)
        mock_previous.return_value = [
            ("v1.3.9", three_days_ago, 1),
            ("v1.3.4", ten_days_ago, 1),
        ]

        metadata = {"version": "1.3.5", "repo_url": "https://github.com/test/repo"}

        result = check_package_update("opencode", metadata)

        assert result is not None
        assert "skipped_version" in result

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_fallback_empty_previous_releases(self, mock_latest, mock_previous):
        """When no previous releases available, return skip info."""
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        now = datetime.now(UTC)
        three_days_ago = (now - timedelta(days=3)).isoformat()

        mock_latest.return_value = ("v1.3.9", three_days_ago, 1)
        mock_previous.return_value = []

        metadata = {"version": "1.3.5", "repo_url": "https://github.com/test/repo"}

        result = check_package_update("opencode", metadata)

        assert result is not None
        assert "skipped_version" in result

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_fallback_api_failure(self, mock_latest, mock_previous):
        """When get_previous_github_releases raises, return skip info."""
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        now = datetime.now(UTC)
        three_days_ago = (now - timedelta(days=3)).isoformat()

        mock_latest.return_value = ("v1.3.9", three_days_ago, 1)
        mock_previous.side_effect = Exception("API error")

        metadata = {"version": "1.3.5", "repo_url": "https://github.com/test/repo"}

        result = check_package_update("opencode", metadata)

        assert result is not None
        assert "skipped_version" in result

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_fallback_skips_releases_without_date(self, mock_latest, mock_previous):
        """Releases without published_at are skipped during fallback."""
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        now = datetime.now(UTC)
        three_days_ago = (now - timedelta(days=3)).isoformat()
        ten_days_ago = (now - timedelta(days=10)).isoformat()

        mock_latest.return_value = ("v1.3.9", three_days_ago, 1)
        mock_previous.return_value = [
            ("v1.3.9", three_days_ago, 1),
            ("v1.3.8", None, 1),
            ("v1.3.7", ten_days_ago, 1),
        ]

        metadata = {"version": "1.3.5", "repo_url": "https://github.com/test/repo"}

        result = check_package_update("opencode", metadata)

        assert result is not None
        assert result["to_version"] == "1.3.7"

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_fallback_walks_multiple_releases(self, mock_latest, mock_previous):
        """Walks back through multiple too-young releases to find an old enough one."""
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        now = datetime.now(UTC)
        two_days_ago = (now - timedelta(days=2)).isoformat()
        four_days_ago = (now - timedelta(days=4)).isoformat()
        six_days_ago = (now - timedelta(days=6)).isoformat()
        fifteen_days_ago = (now - timedelta(days=15)).isoformat()

        mock_latest.return_value = ("v1.3.9", two_days_ago, 1)
        mock_previous.return_value = [
            ("v1.3.9", two_days_ago, 1),
            ("v1.3.8", four_days_ago, 1),
            ("v1.3.7", six_days_ago, 1),
            ("v1.3.6", fifteen_days_ago, 1),
        ]

        metadata = {"version": "1.3.5", "repo_url": "https://github.com/test/repo"}

        result = check_package_update("opencode", metadata)

        assert result is not None
        assert result["to_version"] == "1.3.6"

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_fallback_walk_produces_checked_versions_chain(self, mock_latest, mock_previous):
        """Fallback walk accumulates checked_versions with too_young and selected entries."""
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        now = datetime.now(UTC)
        two_days_ago = (now - timedelta(days=2)).isoformat()
        four_days_ago = (now - timedelta(days=4)).isoformat()
        six_days_ago = (now - timedelta(days=6)).isoformat()
        fifteen_days_ago = (now - timedelta(days=15)).isoformat()

        mock_latest.return_value = ("v1.3.9", two_days_ago, 1)
        mock_previous.return_value = [
            ("v1.3.9", two_days_ago, 1),
            ("v1.3.8", four_days_ago, 1),
            ("v1.3.7", six_days_ago, 1),
            ("v1.3.6", fifteen_days_ago, 1),
        ]

        metadata = {"version": "1.3.5", "repo_url": "https://github.com/test/repo"}

        result = check_package_update("opencode", metadata)

        assert result is not None
        assert "checked_versions" in result
        cv = result["checked_versions"]
        assert cv[0]["version"] == "1.3.9"
        assert cv[0]["status"] == "too_young"
        assert cv[1]["version"] == "1.3.8"
        assert cv[1]["status"] == "too_young"
        assert cv[2]["version"] == "1.3.7"
        assert cv[2]["status"] == "too_young"
        assert cv[3]["version"] == "1.3.6"
        assert cv[3]["status"] == "selected"

    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_direct_update_has_no_checked_versions(self, mock_latest):
        """Direct update path does not include checked_versions."""
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        now = datetime.now(UTC)
        eight_days_ago = (now - timedelta(days=8)).isoformat()

        mock_latest.return_value = ("v1.3.9", eight_days_ago, 1)

        metadata = {"version": "1.3.5", "repo_url": "https://github.com/test/repo"}

        result = check_package_update("opencode", metadata)

        assert result is not None
        assert result["from_version"] == "1.3.5"
        assert result["to_version"] == "1.3.9"
        assert "checked_versions" not in result

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_skip_includes_checked_versions(self, mock_latest, mock_previous):
        """Skip dict includes checked_versions with latest as too_young."""
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        now = datetime.now(UTC)
        three_days_ago = (now - timedelta(days=3)).isoformat()

        mock_latest.return_value = ("v1.3.9", three_days_ago, 1)
        mock_previous.return_value = []

        metadata = {"version": "1.3.5", "repo_url": "https://github.com/test/repo"}

        result = check_package_update("opencode", metadata)

        assert result is not None
        assert "skipped_version" in result
        assert "checked_versions" in result
        cv = result["checked_versions"]
        assert len(cv) == 1
        assert cv[0]["version"] == "1.3.9"
        assert cv[0]["status"] == "too_young"


class TestNoAssetFallback:
    """Test fallback when latest release has no assets (0 assets)."""

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_no_assets_skips_to_previous(self, mock_latest, mock_previous):
        """Release with 0 assets is skipped, falls back to previous with assets."""
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        now = datetime.now(UTC)
        ten_days_ago = (now - timedelta(days=10)).isoformat()

        mock_latest.return_value = ("v2.20.0", ten_days_ago, 0)
        mock_previous.return_value = [
            ("v2.20.0", ten_days_ago, 0),
            ("v2.19.0", ten_days_ago, 1),
        ]

        metadata = {"version": "2.18.0", "repo_url": "https://github.com/test/repo"}

        result = check_package_update("skaffold", metadata)

        assert result is not None
        assert result["package"] == "skaffold"
        assert result["from_version"] == "2.18.0"
        assert result["to_version"] == "2.19.0"

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_no_assets_all_previous_also_no_assets(self, mock_latest, mock_previous):
        """When all previous releases also have 0 assets, return skip info."""
        from tasks.tools._updates import check_package_update

        mock_latest.return_value = ("v2.20.0", None, 0)
        mock_previous.return_value = [
            ("v2.19.0", None, 0),
            ("v2.18.0", None, 0),
        ]

        metadata = {"version": "2.17.0", "repo_url": "https://github.com/test/repo"}

        result = check_package_update("skaffold", metadata)

        assert result is not None
        assert "skipped_version" in result
        assert result["skipped_version"] == "2.20.0"
        assert "no assets" in result["reason"]

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_no_assets_skip_info_includes_checked_versions(self, mock_latest, mock_previous):
        """Skip info includes checked_versions with no_assets status."""
        from tasks.tools._updates import check_package_update

        mock_latest.return_value = ("v2.20.0", None, 0)
        mock_previous.return_value = []

        metadata = {"version": "2.19.0", "repo_url": "https://github.com/test/repo"}

        result = check_package_update("skaffold", metadata)

        assert result is not None
        assert "skipped_version" in result
        assert "checked_versions" in result
        cv = result["checked_versions"]
        assert cv[0]["version"] == "2.20.0"
        assert cv[0]["status"] == "no_assets"

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_no_assets_equal_to_current_returns_none(self, mock_latest, mock_previous):
        """When no-assets release version equals current, return None."""
        from tasks.tools._updates import check_package_update

        mock_latest.return_value = ("v2.19.0", None, 0)
        mock_previous.return_value = []

        metadata = {"version": "2.19.0", "repo_url": "https://github.com/test/repo"}

        result = check_package_update("skaffold", metadata)

        assert result is None

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_no_assets_mixed_with_too_young(self, mock_latest, mock_previous):
        """No-assets releases and too-young releases both skipped in fallback walk."""
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        now = datetime.now(UTC)
        three_days_ago = (now - timedelta(days=3)).isoformat()
        ten_days_ago = (now - timedelta(days=10)).isoformat()

        mock_latest.return_value = ("v2.20.0", three_days_ago, 0)
        mock_previous.return_value = [
            ("v2.20.0", three_days_ago, 0),
            ("v2.19.0", three_days_ago, 1),
            ("v2.18.0", ten_days_ago, 1),
        ]

        metadata = {"version": "2.17.0", "repo_url": "https://github.com/test/repo"}

        result = check_package_update("skaffold", metadata)

        assert result is not None
        assert result["to_version"] == "2.18.0"


class TestHashiCorpExternalHosted:
    """HashiCorp tools (terraform/packer) host binaries on releases.hashicorp.com,
    so their GitHub releases legitimately have zero assets. The asset-count gate
    must not block their updates."""

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_terraform_zero_assets_returns_update(self, mock_latest, mock_previous):
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        now = datetime.now(UTC)
        ten_days_ago = (now - timedelta(days=10)).isoformat()

        mock_latest.return_value = ("v1.15.7", ten_days_ago, 0)
        mock_previous.return_value = []

        metadata = {
            "version": "1.15.3",
            "repo_url": "https://github.com/hashicorp/terraform",
            "download_url": "https://releases.hashicorp.com/{{name}}/{{version}}/{{name}}_{{version}}_{{os}}_{{arch}}.zip",
        }

        result = check_package_update("terraform", metadata)

        assert result is not None
        assert result["package"] == "terraform"
        assert result["from_version"] == "1.15.3"
        assert result["to_version"] == "1.15.7"
        assert "skipped_version" not in result

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    def test_terraform_zero_assets_walks_back(self, mock_latest, mock_previous):
        from datetime import UTC, datetime, timedelta

        from tasks.tools._updates import check_package_update

        now = datetime.now(UTC)
        three_days_ago = (now - timedelta(days=3)).isoformat()
        eight_days_ago = (now - timedelta(days=8)).isoformat()
        fifteen_days_ago = (now - timedelta(days=15)).isoformat()

        mock_latest.return_value = ("v1.15.7", three_days_ago, 0)
        mock_previous.return_value = [
            ("v1.15.7", three_days_ago, 0),
            ("v1.15.6", eight_days_ago, 0),
            ("v1.15.5", fifteen_days_ago, 0),
        ]

        metadata = {
            "version": "1.15.3",
            "repo_url": "https://github.com/hashicorp/terraform",
            "download_url": "https://releases.hashicorp.com/{{name}}/{{version}}/{{name}}_{{version}}_{{os}}_{{arch}}.zip",
        }

        result = check_package_update("terraform", metadata)

        assert result is not None
        assert result["to_version"] == "1.15.6"
        assert "checked_versions" in result
        versions_in_chain = [cv["version"] for cv in result["checked_versions"]]
        assert "1.15.7" in versions_in_chain
        assert "1.15.6" in versions_in_chain


class TestFormatCheckedVersions:
    """Test _format_checked_versions helper."""

    def test_empty_list(self):
        from tasks.tools._updates import _format_checked_versions

        assert _format_checked_versions([]) == ""

    def test_single_entry(self):
        from tasks.tools._updates import _format_checked_versions

        result = _format_checked_versions(
            [{"version": "1.3.9", "age_days": 2, "status": "too_young"}]
        )
        assert result == "v1.3.9 (2d)"

    def test_multiple_entries(self):
        from tasks.tools._updates import _format_checked_versions

        result = _format_checked_versions(
            [
                {"version": "1.3.9", "age_days": 2, "status": "too_young"},
                {"version": "1.3.8", "age_days": 4, "status": "too_young"},
                {"version": "1.3.6", "age_days": 15, "status": "selected"},
            ]
        )
        assert result == "v1.3.9 (2d), v1.3.8 (4d), v1.3.6 (15d)"


class TestDetectUpdatesDisplay:
    """Test detect_updates returns checked_versions data for caller display."""

    @patch("tasks.tools._updates.get_previous_github_releases")
    @patch("tasks.tools._updates.get_latest_github_release_version")
    @patch("tasks.tools._updates.Progress")
    @patch("tasks.tools._updates.Console")
    def test_fallback_update_includes_checked_versions(
        self,
        mock_console_cls,
        mock_progress_cls,
        mock_latest,
        mock_previous,
        sample_metadata,
    ):
        """Fallback update returns checked_versions in update dict for caller display."""
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        two_days_ago = (now - timedelta(days=2)).isoformat()
        ten_days_ago = (now - timedelta(days=10)).isoformat()

        # Make Progress a no-op context manager
        mock_progress = Mock()
        mock_progress.__enter__ = Mock(return_value=mock_progress)
        mock_progress.__exit__ = Mock(return_value=False)
        mock_progress_cls.return_value = mock_progress

        mock_latest.side_effect = [("v2.0.0", two_days_ago, 1), ("v3.0.0", ten_days_ago, 1)]
        mock_previous.side_effect = [
            [("v2.0.0", two_days_ago, 1), ("v1.9.0", ten_days_ago, 1)],
            [],
        ]

        updates, _skipped = detect_updates(sample_metadata)

        assert len(updates) >= 1
        fallback = [u for u in updates if "checked_versions" in u]
        assert len(fallback) == 1
        assert fallback[0]["to_version"] == "1.9.0"


class TestAutomationSkippedDisplay:
    """Test automation skipped packages display with checked_versions."""

    @patch("tasks.tools.update.subprocess.run")
    @patch("tasks.tools.update.metadata_cache")
    @patch("tasks.tools.update.detect_updates")
    @patch("pathlib.Path.read_bytes")
    @patch("pathlib.Path.exists")
    def test_skipped_console_includes_walk_chain(
        self,
        mock_exists,
        mock_read_bytes,
        mock_detect,
        mock_cache,
        mock_subprocess,
        temp_metadata_file,
    ):
        """Console output for skipped packages includes walked chain."""
        from invoke.context import Context
        from tasks.tools import update

        mock_exists.return_value = True
        mock_read_bytes.return_value = b"test-content"

        skip_with_chain = {
            "package": "test-pkg",
            "current_version": "1.0.0",
            "skipped_version": "2.0.0",
            "reason": "too young",
            "checked_versions": [
                {"version": "2.0.0", "age_days": 2, "status": "too_young"},
            ],
        }

        mock_cache.get.return_value = {"test-pkg": {"version": "1.0.0"}}
        mock_cache.clear = Mock()
        mock_detect.return_value = ([], [skip_with_chain])

        def mock_run_side_effect(*args, **kwargs):
            if "rev-parse" in str(args):
                return Mock(stdout="main\n", stderr="", returncode=0)
            return Mock(stdout="", stderr="", returncode=0)

        mock_subprocess.side_effect = mock_run_side_effect

        ctx = Context()
        update(ctx, pr=True, dry_run=True)

    @patch("tasks.tools.update.subprocess.run")
    @patch("tasks.tools.update.subprocess.check_output")
    @patch("tasks.tools.update.metadata_cache")
    @patch("tasks.tools.update.detect_updates")
    @patch("tasks.tools.update.write_metadata")
    @patch("pathlib.Path.read_bytes")
    @patch("pathlib.Path.exists")
    def test_pr_body_includes_checked_versions_header(
        self,
        mock_exists,
        mock_read_bytes,
        mock_write,
        mock_detect,
        mock_cache,
        mock_check_output,
        mock_subprocess,
        temp_metadata_file,
    ):
        """PR body contains Checked Versions column header when skips have chain."""
        from invoke.context import Context
        from tasks.tools import update

        mock_exists.return_value = True
        mock_read_bytes.return_value = b"test-content"

        updates_list = [{"package": "test-pkg", "from_version": "1.0.0", "to_version": "2.0.0"}]
        skip_with_chain = {
            "package": "other-pkg",
            "current_version": "3.0.0",
            "skipped_version": "4.0.0",
            "reason": "too young",
            "checked_versions": [
                {"version": "4.0.0", "age_days": 2, "status": "too_young"},
            ],
        }

        mock_cache.get.return_value = {"test-pkg": {"version": "1.0.0"}}
        mock_cache.clear = Mock()
        mock_detect.return_value = (updates_list, [skip_with_chain])
        mock_check_output.return_value = "1"

        gh_commands = []
        captured_body = None

        def mock_run_side_effect(*args, **kwargs):
            nonlocal captured_body
            cmd = args[0] if args else kwargs.get("args", [])
            gh_commands.append(cmd)
            if "rev-parse" in str(cmd):
                return Mock(stdout="main\n", stderr="", returncode=0)
            if isinstance(cmd, list) and "pr" in cmd and "create" in cmd:
                if "--body-file" in cmd:
                    captured_body = Path(cmd[cmd.index("--body-file") + 1]).read_text()
                return Mock(
                    stdout="https://github.com/test/repo/pull/1\n",
                    stderr="",
                    returncode=0,
                )
            return Mock(stdout="", stderr="", returncode=0)

        mock_subprocess.side_effect = mock_run_side_effect

        ctx = Context()
        update(ctx, pr=True, dry_run=False)

        pr_create_calls = [
            c for c in gh_commands if isinstance(c, list) and "pr" in c and "create" in c
        ]
        assert len(pr_create_calls) >= 1, f"Expected a PR create command, got: {gh_commands}"

        pr_cmd = pr_create_calls[0]
        assert "--body-file" in pr_cmd, f"Expected --body-file in command: {pr_cmd}"
        assert captured_body is not None, "Body file content was not captured"

        assert "Checked Versions" in captured_body
        assert "v4.0.0 (2d)" in captured_body


class TestExtractSemverFromTag:
    """Test extract_semver_from_tag helper."""

    @pytest.mark.parametrize(
        ("tag", "expected"),
        [
            ("v1.2.3", "1.2.3"),
            ("1.2.3", "1.2.3"),
            ("V1.2.3", "1.2.3"),
            ("v1.2.3-rc1", "1.2.3-rc1"),
            ("v1.2.3+k3s1", "1.2.3+k3s1"),
            ("v1.2.3-rc1+build.4", "1.2.3-rc1+build.4"),
            ("kustomize/v5.3.0", "5.3.0"),
            ("cli/cli-v2.50.0", "2.50.0"),
            ("latest", None),
            ("", None),
            ("v1", None),
            ("1.2", None),
        ],
    )
    def test_extract_semver(self, tag, expected):
        assert extract_semver_from_tag(tag) == expected


class TestExtractVersionFromTag:
    """Test extract_version_from_tag helper (semver + CalVer)."""

    @pytest.mark.parametrize(
        ("tag", "expected"),
        [
            # Semver passes through unchanged
            ("v1.2.3", "1.2.3"),
            ("1.2.3-rc1", "1.2.3-rc1"),
            ("kustomize/v5.3.0", "5.3.0"),
            # CalVer tags (leading zeros preserved for URL rendering)
            ("2026.08.29.2", "2026.08.29.2"),
            ("2026.08.29", "2026.08.29"),
            ("v2026.08.29", "2026.08.29"),
            ("2026.8.7", "2026.8.7"),
            ("release-2026.08.29", "2026.08.29"),
            # Semver takes precedence when both patterns could match
            ("1234.5.6", "1234.5.6"),
            # No version at all
            ("latest", None),
            ("", None),
            ("v1", None),
            ("1.2", None),
        ],
    )
    def test_extract_version(self, tag, expected):
        assert extract_version_from_tag(tag) == expected


class TestCompareVersions:
    """Test compare_versions helper (semver + CalVer)."""

    @pytest.mark.parametrize(
        ("left", "right", "expected"),
        [
            # Strict semver semantics
            ("1.2.3", "1.4.0", -1),
            ("1.2.3", "1.2.3", 0),
            ("1.2.3-rc.1", "1.2.3", -1),
            ("2.0.0", "10.0.0", -1),
            # CalVer numeric component comparison
            ("2026.08.29.2", "2026.08.29.10", -1),
            ("2026.09.01", "2026.08.31", 1),
            ("2026.08.29", "2026.08.29", 0),
            ("2027.01.01", "2026.12.31", 1),
            # Incomparable (semver prerelease vs CalVer)
            ("1.2.3-rc.1", "2026.08.29", None),
        ],
    )
    def test_compare(self, left, right, expected):
        assert compare_versions(left, right) == expected


class TestLogging:
    """Test logging behavior in exception handlers."""

    @patch("tasks.tools._updates.get_previous_github_releases", side_effect=Exception("boom"))
    def test_try_previous_release_logs_failure(self, mock_prev, caplog):
        import logging

        from tasks.tools._updates import _try_previous_release

        with caplog.at_level(logging.WARNING, logger="tasks.tools._updates"):
            result, checked = _try_previous_release("test", "owner", "repo", "1.0.0")

        assert result is None
        assert checked == []
        assert "Failed to fetch previous releases" in caplog.text

    @patch("tasks.tools._updates.get_latest_github_release_version", side_effect=Exception("boom"))
    def test_check_package_update_logs_failure(self, mock_latest, caplog):
        import logging

        from tasks.tools._updates import check_package_update

        with caplog.at_level(logging.WARNING, logger="tasks.tools._updates"):
            result = check_package_update(
                "test", {"version": "1.0.0", "repo_url": "https://github.com/o/r"}
            )

        assert result is None
        assert "Failed to check update" in caplog.text
