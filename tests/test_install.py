from pathlib import Path
from unittest.mock import Mock

import pytest
from tasks.lib import PackageDownloader


class TestPackageDownloader:
    """Test PackageDownloader class."""

    def test_initialization(self):
        """Test PackageDownloader initialization."""
        mock_ctx = Mock()
        downloader = PackageDownloader(
            mock_ctx, "test-pkg", "https://example.com/file.tar.gz", "/tmp"
        )

        assert downloader._package_name == "test-pkg"
        assert downloader._download_url == "https://example.com/file.tar.gz"
        assert downloader._install_path == "/tmp"
        assert downloader._package_exe == "test-pkg"

    def test_initialization_with_custom_exe(self):
        """Test PackageDownloader initialization with custom executable name."""
        mock_ctx = Mock()
        downloader = PackageDownloader(
            mock_ctx, "test-pkg", "https://example.com/file.tar.gz", "/tmp", "custom-exe"
        )

        assert downloader._package_exe == "custom-exe"


class TestPackageDownloaderPackageDir:
    """Test package_dir install behavior."""

    def test_initialization_package_dir_default(self):
        """package_dir defaults to False."""
        downloader = PackageDownloader(Mock(), "pi", "https://example.com/pi.tar.gz", "/tmp")

        assert downloader._package_dir is False

    def test_initialization_package_dir_true(self):
        """package_dir is stored when passed."""
        downloader = PackageDownloader(
            Mock(), "pi", "https://example.com/pi.tar.gz", "/tmp", package_dir=True
        )

        assert downloader._package_dir is True

    def test_download_tar_gz_dir_command_sequence(self, tmp_path):
        """package_dir install copies the archive dir and symlinks the executable."""
        mock_ctx = Mock()

        def fake_run(command: str, **kwargs) -> None:
            if command.startswith("tar -zx"):
                extract_root = Path(command.split(" -C ")[1].split(" ")[0])
                (extract_root / "pi").mkdir()

        mock_ctx.run.side_effect = fake_run
        downloader = PackageDownloader(
            mock_ctx,
            "pi",
            "https://example.com/pi-linux-x64.tar.gz",
            str(tmp_path),
            package_dir=True,
        )
        downloader.download()

        commands = [call.args[0] for call in mock_ctx.run.call_args_list]
        assert any(
            cmd.startswith("cp -a ") and cmd.endswith(f" {tmp_path}/pi.d") for cmd in commands
        )
        assert f"chmod -v +x {tmp_path}/pi.d/pi" in commands
        assert f"ln -sfn pi.d/pi {tmp_path}/pi" in commands
        assert f"rm -rf {tmp_path}/pi.d" in commands

    def test_download_tar_gz_dir_requires_top_level_dir(self, tmp_path):
        """A clear error is raised when the archive has no '<name>/' top-level dir."""
        mock_ctx = Mock()
        downloader = PackageDownloader(
            mock_ctx,
            "pi",
            "https://example.com/pi.tar.gz",
            str(tmp_path),
            package_dir=True,
        )

        with pytest.raises(RuntimeError, match="no top-level 'pi/' directory"):
            downloader.download()


class TestInstallSinglePackageForce:
    """Test force-reinstall cleanup for directory-based packages."""

    def test_force_reinstall_removes_symlink_and_package_dir(self, tmp_path, monkeypatch):
        """Force removes the '<name>' symlink and the '<name>.d' dir before downloading."""
        from tasks.tools import _install

        name = "pi"
        tool_dir = tmp_path / f"{name}.d"
        tool_dir.mkdir()
        exe = tool_dir / name
        exe.write_text("#!/bin/sh\n")
        link = tmp_path / name
        link.symlink_to(exe)

        stub_kwargs: dict = {}

        class StubDownloader:
            def __init__(self, ctx, **kwargs) -> None:
                stub_kwargs.update(kwargs)

            def download(self) -> None:
                assert not link.is_symlink(), "symlink must be removed before download"
                assert not tool_dir.exists(), "package dir must be removed before download"

        monkeypatch.setattr(_install, "PackageDownloader", StubDownloader)
        monkeypatch.setattr(
            _install.metadata_cache,
            "get",
            lambda: {
                name: {
                    "description": "test tool",
                    "download_url": "https://example.com/pi.tar.gz",
                    "repo_url": "https://github.com/earendil-works/pi",
                    "license": "MIT",
                    "version": "1.0.0",
                    "package_dir": True,
                }
            },
        )

        _install.install_single_package(Mock(), name, tmp_path, force=True)

        assert stub_kwargs["package_dir"] is True
