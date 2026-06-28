import hashlib
from pathlib import Path
from unittest.mock import Mock
import zipfile

import pytest
from tasks.lib import IntegrityError, PackageDownloader, verify_file_sha256


class TestSHA256:
    """Tests for verify_file_sha256 utility function."""

    def test_correct_hash_passes(self, tmp_path: Path) -> None:
        """Verification passes when hash matches file content."""
        file_path = tmp_path / "test.bin"
        content = b"hello world"
        file_path.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        verify_file_sha256(file_path, expected)

    def test_wrong_hash_raises_integrity_error(self, tmp_path: Path) -> None:
        """IntegrityError raised when hash doesn't match."""
        file_path = tmp_path / "test.bin"
        file_path.write_bytes(b"real content")

        with pytest.raises(IntegrityError):
            verify_file_sha256(file_path, "0000deadbeef", package_name="test-pkg")

    @pytest.mark.parametrize("skip_value", [None, ""])
    def test_skip_verification(self, tmp_path: Path, skip_value: str | None) -> None:
        """No verification when expected_hash is None or empty string."""
        file_path = tmp_path / "test.bin"
        file_path.write_bytes(b"any content")

        verify_file_sha256(file_path, skip_value)
        assert file_path.exists()

    def test_uppercase_hash_normalized(self, tmp_path: Path) -> None:
        """Uppercase hex digest still matches."""
        file_path = tmp_path / "test.bin"
        content = b"normalize me"
        file_path.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest().upper()
        verify_file_sha256(file_path, expected)

    def test_whitespace_hash_stripped(self, tmp_path: Path) -> None:
        """Hash with trailing whitespace still matches."""
        file_path = tmp_path / "test.bin"
        content = b"strip whitespace"
        file_path.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest() + " \n"
        verify_file_sha256(file_path, expected)

    def test_large_file_chunked_reading(self, tmp_path: Path) -> None:
        """Correct hash for file larger than 8192 bytes."""
        file_path = tmp_path / "large.bin"
        content = b"x" * 10_000
        file_path.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        verify_file_sha256(file_path, expected)

    def test_integrity_error_contains_context(self, tmp_path: Path) -> None:
        """IntegrityError message includes tool name, expected, actual hashes."""
        file_path = tmp_path / "test.bin"
        content = b"some content"
        file_path.write_bytes(content)

        actual_hash = hashlib.sha256(content).hexdigest()
        wrong_hash = "deadbeef"

        with pytest.raises(IntegrityError) as exc_info:
            verify_file_sha256(file_path, wrong_hash, package_name="test-pkg")

        error = exc_info.value
        assert "test-pkg" in str(error)
        assert wrong_hash in str(error)
        assert actual_hash in str(error)

    def test_mismatched_file_deleted(self, tmp_path: Path) -> None:
        """Downloaded file is deleted when verification fails."""
        file_path = tmp_path / "test.bin"
        file_path.write_bytes(b"will be deleted")

        assert file_path.exists()
        with pytest.raises(IntegrityError):
            verify_file_sha256(file_path, "wrong_hash")

        assert not file_path.exists()


def _make_downloader(
    tmp_path: Path,
    url: str = "https://example.com/test.tar.gz",
    sha256: str | None = None,
) -> tuple[Mock, PackageDownloader]:
    """Create a PackageDownloader with mocked context."""
    ctx = Mock()
    dl = PackageDownloader(ctx, "test-pkg", url, str(tmp_path), sha256=sha256)
    return ctx, dl


def _sha256_of(data: bytes) -> str:
    """Return hex sha256 digest of data."""
    return hashlib.sha256(data).hexdigest()


class TestPackageDownloaderSHA256:
    """Tests for sha256 verification integration in PackageDownloader.

    These tests verify that PackageDownloader properly verifies sha256
    checksums during download. They mock _ctx.run() to avoid real shell
    execution. All tests should FAIL until Task 4 adds sha256 support.
    """

    def test_init_accepts_sha256_parameter(self) -> None:
        """PackageDownloader.__init__ stores sha256 parameter."""
        ctx = Mock()
        dl = PackageDownloader(
            ctx,
            "test-pkg",
            "https://example.com/file",
            "/tmp",
            sha256="a" * 64,
        )
        assert dl._sha256 == "a" * 64

    def test_init_sha256_defaults_to_none(self) -> None:
        """PackageDownloader.__init__ defaults sha256 to None when not provided."""
        ctx = Mock()
        dl = PackageDownloader(ctx, "test-pkg", "https://example.com/file", "/tmp")
        assert dl._sha256 is None

    def test_download_binary_correct_hash_passes(self, tmp_path: Path) -> None:
        """Binary download with correct sha256 succeeds."""
        content = b"binary-content-for-hash-test"
        expected_hash = _sha256_of(content)

        ctx = Mock()

        def fake_run(cmd: str, **_kwargs: object) -> None:
            if "curl" in cmd and "-o" in cmd:
                # Extract destination path from curl command
                parts = cmd.split()
                dest_idx = parts.index("-o") + 1
                dest = parts[dest_idx]
                Path(dest).write_bytes(content)

        ctx.run = Mock(side_effect=fake_run)

        dl = PackageDownloader(
            ctx,
            "test-pkg",
            "https://example.com/test-pkg",
            str(tmp_path),
            sha256=expected_hash,
        )
        # Should NOT raise — hash matches
        dl.download_binary()

    def test_download_binary_wrong_hash_raises_integrity_error(self, tmp_path: Path) -> None:
        """Binary download with wrong sha256 raises IntegrityError."""
        content = b"binary-content"
        wrong_hash = "b" * 64

        ctx = Mock()

        def fake_run(cmd: str, **_kwargs: object) -> None:
            if "curl" in cmd and "-o" in cmd:
                parts = cmd.split()
                dest_idx = parts.index("-o") + 1
                dest = parts[dest_idx]
                Path(dest).write_bytes(content)

        ctx.run = Mock(side_effect=fake_run)

        dl = PackageDownloader(
            ctx,
            "test-pkg",
            "https://example.com/test-pkg",
            str(tmp_path),
            sha256=wrong_hash,
        )
        with pytest.raises(IntegrityError):
            dl.download_binary()

        # Downloaded file should be cleaned up on failure
        assert not (tmp_path / "test-pkg").exists()

    def test_download_binary_none_hash_skips_verification(self, tmp_path: Path) -> None:
        """Binary download with sha256=None skips verification."""
        ctx = Mock()
        dl = PackageDownloader(
            ctx,
            "test-pkg",
            "https://example.com/test-pkg",
            str(tmp_path),
            sha256=None,
        )
        # Should not raise — no verification performed
        dl.download_binary()

    def test_download_tar_gz_correct_hash(self, tmp_path: Path) -> None:
        """tar.gz download with correct sha256 succeeds."""
        content = b"tar-gz-content-for-hash-test"
        expected_hash = _sha256_of(content)

        ctx = Mock()

        def fake_run(cmd: str, **_kwargs: object) -> None:
            if "curl" in cmd and "-o" in cmd:
                # Write to a temp file that tar would use
                parts = cmd.split()
                dest_idx = parts.index("-o") + 1
                dest = parts[dest_idx]
                Path(dest).write_bytes(content)

        ctx.run = Mock(side_effect=fake_run)

        dl = PackageDownloader(
            ctx,
            "test-pkg",
            "https://example.com/test-pkg.tar.gz",
            str(tmp_path),
            sha256=expected_hash,
        )
        # Should NOT raise — hash matches
        dl.download_tar_gz()

    def test_download_tar_gz_wrong_hash_raises(self, tmp_path: Path) -> None:
        """tar.gz download with wrong sha256 raises IntegrityError."""
        content = b"tar-gz-content"
        wrong_hash = "c" * 64

        ctx = Mock()

        def fake_run(cmd: str, **_kwargs: object) -> None:
            if "curl" in cmd and "-o" in cmd:
                parts = cmd.split()
                dest_idx = parts.index("-o") + 1
                dest = parts[dest_idx]
                Path(dest).write_bytes(content)

        ctx.run = Mock(side_effect=fake_run)

        dl = PackageDownloader(
            ctx,
            "test-pkg",
            "https://example.com/test-pkg.tar.gz",
            str(tmp_path),
            sha256=wrong_hash,
        )
        with pytest.raises(IntegrityError):
            dl.download_tar_gz()

    def test_download_zip_correct_hash(self, tmp_path: Path) -> None:
        """zip download with correct sha256 succeeds."""
        import io

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("test-pkg", "dummy-binary")
        zip_content = buf.getvalue()
        expected_hash = hashlib.sha256(zip_content).hexdigest()

        ctx = Mock()

        def fake_run(cmd: str, **_kwargs: object) -> None:
            if "curl" in cmd and "-o" in cmd:
                parts = cmd.split()
                dest_idx = parts.index("-o") + 1
                dest = parts[dest_idx]
                Path(dest).write_bytes(zip_content)

        ctx.run = Mock(side_effect=fake_run)

        dl = PackageDownloader(
            ctx,
            "test-pkg",
            "https://example.com/test-pkg.zip",
            str(tmp_path),
            sha256=expected_hash,
        )
        dl.download_zip()
