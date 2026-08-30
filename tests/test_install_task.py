from pathlib import Path
from unittest.mock import Mock, patch

from invoke.context import Context
import pytest


class TestInstallTask:
    """Test the consolidated install task."""

    def test_check_required_tools_success(self):
        """Test that required tools check passes when all tools available."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = True
            from tasks.tools._install import check_required_tools

            # Should not raise
            check_required_tools("https://example.com/package.tar.gz")

    def test_check_required_tools_missing_curl(self):
        """Test that missing curl raises error."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = False
            from tasks.tools._install import check_required_tools

            with pytest.raises(RuntimeError, match="Required tool 'curl' not found"):
                check_required_tools("https://example.com/package.bin")

    def test_check_required_tools_error_includes_package_name(self):
        """Missing-tool error includes the package name when provided."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = False
            from tasks.tools._install import check_required_tools

            with pytest.raises(RuntimeError, match=r"required for 'mytool'"):
                check_required_tools("https://example.com/x.zip", package_name="mytool")

    def test_resolve_local_install_path_in_path(self):
        """Test local path resolution when .local/bin is in PATH."""
        test_home = Path("/home/user")

        with (
            patch("tasks.tools._install.Path.home", return_value=test_home),
            patch("os.getenv") as mock_getenv,
        ):
            mock_getenv.return_value = "/usr/local/bin:/home/user/.local/bin"
            from tasks.tools._install import resolve_install_path

            # Mock exists on Path object to return True for .local/bin
            original_exists = Path.exists

            def exists_side_effect(self_arg):
                if str(self_arg) == str(test_home / ".local" / "bin"):
                    return True
                return original_exists(self_arg)

            with patch.object(Path, "exists", exists_side_effect):
                result = resolve_install_path(local=True)
                assert result == test_home / ".local" / "bin"

    def test_resolve_local_install_path_fallback(self):
        """Test local path resolution falls back to ~/bin."""
        with patch("os.getenv") as mock_getenv:
            mock_getenv.return_value = "/usr/local/bin"
            from tasks.tools._install import resolve_install_path

            result = resolve_install_path(local=True)
            assert result == Path.home() / "bin"

    def test_resolve_dist_install_path(self):
        """Test dist path resolution."""
        from tasks.tools._install import resolve_install_path

        result = resolve_install_path(dist=True)
        from tasks.lib import ROOT_DIR

        assert result == ROOT_DIR / "dist"


TOOL_METADATA = {
    "mytool": {"download_url": "https://example.com/{{name}}", "version": "1.0.0"},
}


class TestInstallSinglePackage:
    """Test install_single_package error handling and verbose passthrough."""

    def test_download_failure_wraps_error_with_package_name(self, tmp_path: Path) -> None:
        """Generic download errors are wrapped with package name and URL."""
        from tasks.tools._install import install_single_package

        with (
            patch("tasks.tools._install.metadata_cache") as mock_cache,
            patch("tasks.tools._install.PackageDownloader") as mock_dl_class,
            patch("tasks.tools._install.check_required_tools"),
        ):
            mock_cache.get.return_value = TOOL_METADATA
            mock_dl_class.return_value.download.side_effect = RuntimeError("network boom")

            with pytest.raises(RuntimeError, match=r"Failed to install 'mytool'"):
                install_single_package(Mock(), "mytool", tmp_path)

    def test_integrity_error_not_wrapped(self, tmp_path: Path) -> None:
        """IntegrityError passes through unwrapped (already has package context)."""
        from tasks.lib.integrity import IntegrityError
        from tasks.tools._install import install_single_package

        with (
            patch("tasks.tools._install.metadata_cache") as mock_cache,
            patch("tasks.tools._install.PackageDownloader") as mock_dl_class,
            patch("tasks.tools._install.check_required_tools"),
        ):
            mock_cache.get.return_value = TOOL_METADATA
            mock_dl_class.return_value.download.side_effect = IntegrityError(
                "mytool", "abc", "def", "/tmp/x"
            )

            with pytest.raises(IntegrityError):
                install_single_package(Mock(), "mytool", tmp_path)

    def test_verbose_flag_forwarded_to_downloader(self, tmp_path: Path) -> None:
        """verbose=True is passed through to PackageDownloader."""
        from tasks.tools._install import install_single_package

        with (
            patch("tasks.tools._install.metadata_cache") as mock_cache,
            patch("tasks.tools._install.PackageDownloader") as mock_dl_class,
            patch("tasks.tools._install.check_required_tools"),
        ):
            mock_cache.get.return_value = TOOL_METADATA
            install_single_package(Mock(), "mytool", tmp_path, verbose=True)

            _, kwargs = mock_dl_class.call_args
            assert kwargs["verbose"] is True

    def test_force_reinstall_removes_existing_file_target(self, tmp_path: Path) -> None:
        """force=True over an installed binary (a plain file) must unlink it, not rmtree."""
        from tasks.tools._install import install_single_package

        (tmp_path / "mytool").write_text("old binary")

        with (
            patch("tasks.tools._install.metadata_cache") as mock_cache,
            patch("tasks.tools._install.PackageDownloader") as mock_dl_class,
            patch("tasks.tools._install.check_required_tools"),
        ):
            mock_cache.get.return_value = TOOL_METADATA
            install_single_package(Mock(), "mytool", tmp_path, force=True)

            mock_dl_class.return_value.download.assert_called_once()

    def test_force_reinstall_removes_existing_directory_target(self, tmp_path: Path) -> None:
        """force=True over an installed tool directory must remove the directory tree."""
        from tasks.tools._install import install_single_package

        stale_dir = tmp_path / "mytool"
        stale_dir.mkdir()
        (stale_dir / "nested").write_text("stale")

        with (
            patch("tasks.tools._install.metadata_cache") as mock_cache,
            patch("tasks.tools._install.PackageDownloader") as mock_dl_class,
            patch("tasks.tools._install.check_required_tools"),
        ):
            mock_cache.get.return_value = TOOL_METADATA
            install_single_package(Mock(), "mytool", tmp_path, force=True)

            mock_dl_class.return_value.download.assert_called_once()

    def test_force_uses_shutil_rmtree(self, tmp_path: Path) -> None:
        """--force removes an existing install via shutil.rmtree, not a shell rm."""
        from tasks.tools._install import install_single_package

        (tmp_path / "oldtool").mkdir()
        ctx = Mock()
        meta = {"oldtool": {"download_url": "https://example.com/x", "version": "1.0.0"}}

        with (
            patch("tasks.tools._install.metadata_cache") as mock_cache,
            patch("tasks.tools._install.shutil.rmtree") as mock_rmtree,
            patch("tasks.tools._install.PackageDownloader"),
            patch("tasks.tools._install.check_required_tools"),
        ):
            mock_cache.get.return_value = meta
            install_single_package(ctx, "oldtool", tmp_path, force=True)

            mock_rmtree.assert_called_once_with(tmp_path / "oldtool")
            ctx.run.assert_not_called()

    def test_already_installed_skips_download(self, tmp_path: Path) -> None:
        """When the tool already exists, the downloader is not invoked."""
        from tasks.tools._install import install_single_package

        (tmp_path / "mytool").mkdir()

        with (
            patch("tasks.tools._install.metadata_cache") as mock_cache,
            patch("tasks.tools._install.PackageDownloader") as mock_dl_class,
            patch("tasks.tools._install.check_required_tools"),
        ):
            mock_cache.get.return_value = TOOL_METADATA
            install_single_package(Mock(), "mytool", tmp_path)

            mock_dl_class.assert_not_called()

    def test_unknown_tool_raises_value_error(self, tmp_path: Path) -> None:
        """Unknown tool name raises ValueError before any download."""
        from tasks.tools._install import install_single_package

        with patch("tasks.tools._install.metadata_cache") as mock_cache:
            mock_cache.get.return_value = {}
            with pytest.raises(ValueError, match="not found in metadata"):
                install_single_package(Mock(), "nope", tmp_path)


class TestBulkInstall:
    """Test the install task's bulk loop resilience and summary."""

    def test_bulk_install_continues_on_failure(self, tmp_path: Path) -> None:
        """One package failure does not abort remaining packages."""
        from invoke.exceptions import Exit
        from tasks.tools.install import install

        metadata = {
            "tool1": {"download_url": "https://example.com/a", "version": "1.0.0"},
            "tool2": {"download_url": "https://example.com/b", "version": "1.0.0"},
            "tool3": {"download_url": "https://example.com/c", "version": "1.0.0"},
        }
        attempted: list[str] = []

        def fake_install(c, name, path, force=False, verbose=False):
            attempted.append(name)
            if name == "tool2":
                raise RuntimeError("boom")

        with (
            patch("tasks.tools.install.metadata_cache") as mock_cache,
            patch("tasks.tools.install.install_single_package", side_effect=fake_install),
            patch("tasks.tools.install.resolve_install_path", return_value=tmp_path),
        ):
            mock_cache.get.return_value = metadata
            with pytest.raises(Exit):
                install(Context())

        assert attempted == ["tool1", "tool2", "tool3"]

    def test_bulk_install_no_exit_when_all_succeed(self, tmp_path: Path) -> None:
        """No Exit raised when every package installs successfully."""
        from tasks.tools.install import install

        metadata = {
            "tool1": {"download_url": "https://example.com/a", "version": "1.0.0"},
            "tool2": {"download_url": "https://example.com/b", "version": "1.0.0"},
        }

        with (
            patch("tasks.tools.install.metadata_cache") as mock_cache,
            patch("tasks.tools.install.install_single_package"),
            patch("tasks.tools.install.resolve_install_path", return_value=tmp_path),
        ):
            mock_cache.get.return_value = metadata
            install(Context())

    def test_bulk_install_clears_cache_in_finally(self, tmp_path: Path) -> None:
        """metadata_cache.clear() runs even when a package fails."""
        from invoke.exceptions import Exit
        from tasks.tools.install import install

        metadata = {"tool1": {"download_url": "https://example.com/a", "version": "1.0.0"}}

        with (
            patch("tasks.tools.install.metadata_cache") as mock_cache,
            patch(
                "tasks.tools.install.install_single_package",
                side_effect=RuntimeError("boom"),
            ),
            patch("tasks.tools.install.resolve_install_path", return_value=tmp_path),
        ):
            mock_cache.get.return_value = metadata
            with pytest.raises(Exit):
                install(Context())

            mock_cache.clear.assert_called_once()
