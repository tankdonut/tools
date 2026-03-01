from unittest.mock import Mock, patch

from tasks.update import detect_updates, get_latest_github_release_version, get_owner_and_repo


class TestDetectUpdates:
    """Test detect_updates function."""

    @patch("tasks.update.get_latest_github_release_version")
    def test_detect_updates_found(self, mock_latest, sample_metadata):
        """Test detecting updates when newer versions exist."""
        mock_latest.side_effect = ["v2.1.0", "v3.0.0"]
        updates = detect_updates(sample_metadata)

        assert len(updates) == 2
        assert updates[0]["package"] == "test-pkg1"
        assert updates[0]["from_version"] == "1.0.0"
        assert updates[0]["to_version"] == "2.1.0"

    @patch("tasks.update.get_latest_github_release_version")
    def test_detect_updates_none_found(self, mock_latest, sample_metadata):
        """Test when no updates are available."""
        mock_latest.side_effect = ["v1.0.0", "v2.0.0"]
        updates = detect_updates(sample_metadata)

        assert len(updates) == 0

    @patch("tasks.update.get_latest_github_release_version")
    def test_detect_updates_invalid_version(self, mock_latest, sample_metadata):
        """Test handling of invalid version tags."""
        mock_latest.side_effect = ["invalid-tag", "v3.0.0"]
        updates = detect_updates(sample_metadata)

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

    @patch("tasks.update.requests.get")
    def test_success(self, mock_get):
        """Test successful API call."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"tag_name": "v1.2.3"}
        mock_get.return_value = mock_response

        version = get_latest_github_release_version("test", "repo")
        assert version == "v1.2.3"

    @patch("tasks.update.requests.get")
    def test_with_auth_token(self, mock_get, monkeypatch):
        """Test API call with authentication token."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"tag_name": "v1.2.3"}
        mock_get.return_value = mock_response

        get_latest_github_release_version("test", "repo")

        call_args = mock_get.call_args
        assert "Authorization" in call_args.kwargs["headers"]
        assert call_args.kwargs["headers"]["Authorization"] == "Bearer test-token"

    @patch("tasks.update.requests.get")
    def test_failure_status_code(self, mock_get):
        """Test handling of non-200 status codes."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        version = get_latest_github_release_version("test", "repo")
        assert version is None


class TestAutomationDryRun:
    """Test automation task dry-run mode."""

    @patch("tasks.update.subprocess.run")
    @patch("tasks.update.metadata_cache")
    @patch("tasks.update.detect_updates")
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
        from tasks.update import automation

        mock_exists.return_value = True
        mock_read_bytes.return_value = b"test-content"

        updates_list = [{"package": "test-pkg", "from_version": "1.0.0", "to_version": "2.0.0"}]

        mock_cache.get.return_value = {"test-pkg": {"version": "1.0.0"}}
        mock_cache.clear = Mock()
        mock_detect.return_value = updates_list

        # Mock git commands
        def mock_run_side_effect(*args, **kwargs):
            if "rev-parse" in str(args):
                return Mock(stdout="main\n", stderr="", returncode=0)
            return Mock(stdout="", stderr="", returncode=0)

        mock_subprocess.side_effect = mock_run_side_effect

        # Run automation in dry-run mode with proper Context
        ctx = Context()
        automation(ctx, ci=False, dry_run=True)

        # In dry-run mode, NO git operations should be called
        # The function returns early before any git commands
        git_calls = [str(git_call) for git_call in mock_subprocess.call_args_list]

        # Should NOT have called ANY git operations
        assert not any("git" in git_call for git_call in git_calls)

    @patch("tasks.update.subprocess.run")
    @patch("tasks.update.metadata_cache")
    @patch("tasks.update.detect_updates")
    @patch("tasks.update.write_metadata")
    @patch("tasks.update.subprocess.check_output")
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
        from tasks.update import automation

        mock_cache.get.return_value = {"test-pkg": {"version": "1.0.0"}}
        mock_cache.clear = Mock()
        mock_detect.return_value = [
            {"package": "test-pkg", "from_version": "1.0.0", "to_version": "2.0.0"}
        ]

        def mock_run_side_effect(*args, **kwargs):
            if "rev-parse" in str(args):
                return Mock(stdout="main\n", stderr="", returncode=0)
            return Mock(stdout="", stderr="", returncode=0)

        mock_subprocess.side_effect = mock_run_side_effect
        mock_check_output.return_value = "1"

        # Run automation in dry-run mode with proper Context
        ctx = Context()
        automation(ctx, ci=False, dry_run=True)

        # Verify write_metadata was not called
        mock_write.assert_not_called()
