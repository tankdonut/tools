from unittest.mock import patch

from tasks.lib import get_goarch, get_rust_arch


class TestGoArch:
    """Test get_goarch function."""

    @patch("platform.machine")
    def test_x86_64(self, mock_machine):
        """Test x86_64 architecture."""
        mock_machine.return_value = "x86_64"
        assert get_goarch() == "amd64"

    @patch("platform.machine")
    def test_aarch64(self, mock_machine):
        """Test ARM64 architecture."""
        mock_machine.return_value = "aarch64"
        assert get_goarch() == "arm64"


class TestRustArch:
    """Test get_rust_arch function."""

    @patch("platform.machine")
    def test_x86_64(self, mock_machine):
        """Test x86_64 architecture."""
        mock_machine.return_value = "x86_64"
        assert get_rust_arch() == "x86_64"

    @patch("platform.machine")
    def test_armv7l(self, mock_machine):
        """Test ARMv7 architecture."""
        mock_machine.return_value = "armv7l"
        assert get_rust_arch() == "arm"
