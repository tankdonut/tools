from unittest.mock import Mock

from tasks.install.download import PackageDownloader


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
