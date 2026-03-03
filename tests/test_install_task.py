from pathlib import Path

from unittest.mock import patch

import pytest


class TestInstallTask:
    """Test the consolidated install task."""

    def test_check_required_tools_success(self):
        """Test that required tools check passes when all tools available."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = True
            from tasks.install import check_required_tools

            # Should not raise
            check_required_tools("https://example.com/package.tar.gz")

    def test_check_required_tools_missing_curl(self):
        """Test that missing curl raises error."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = False
            from tasks.install import check_required_tools

            with pytest.raises(RuntimeError, match="Required tool 'curl' not found"):
                check_required_tools("https://example.com/package.bin")

    def test_resolve_local_install_path_in_path(self):
        """Test local path resolution when .local/bin is in PATH."""
        test_home = Path("/home/user")

        with (
            patch("tasks.install.Path.home", return_value=test_home),
            patch("os.getenv") as mock_getenv,
        ):
            mock_getenv.return_value = "/usr/local/bin:/home/user/.local/bin"
            from tasks.install import resolve_install_path

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
            from tasks.install import resolve_install_path

            result = resolve_install_path(local=True)
            assert result == Path.home() / "bin"

    def test_resolve_dist_install_path(self):
        """Test dist path resolution."""
        from tasks.install import resolve_install_path

        result = resolve_install_path(dist=True)
        from tasks.lib import ROOT_DIR

        assert result == ROOT_DIR / "dist"
