import hashlib
from pathlib import Path


class IntegrityError(Exception):
    """SHA256 integrity verification failed."""

    def __init__(
        self,
        package_name: str,
        expected_hash: str,
        actual_hash: str,
        file_path: str | Path,
    ) -> None:
        self.package_name = package_name
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        self.file_path = str(file_path)
        super().__init__(
            f"SHA256 mismatch for '{package_name}': "
            f"expected {expected_hash}, got {actual_hash} "
            f"(file: {self.file_path})"
        )


def verify_file_sha256(
    file_path: str | Path,
    expected_hash: str | None,
    package_name: str = "",
) -> None:
    """Verify SHA256 checksum of a downloaded file.

    Args:
        file_path: Path to the file to verify.
        expected_hash: Expected SHA256 hex digest. If None or empty, skip verification.
        package_name: Package name for error messages.

    Raises:
        IntegrityError: If hash doesn't match.
    """
    if not expected_hash:
        return

    expected = expected_hash.strip().lower()

    sha256 = hashlib.sha256()
    with Path(file_path).open("rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    actual = sha256.hexdigest()

    if actual != expected:
        Path(file_path).unlink(missing_ok=True)
        raise IntegrityError(package_name, expected, actual, file_path)
