import re

import semver

from tasks.lib.digests import DIGEST_FALLBACK as DIGEST_FALLBACK
from tasks.lib.digests import _extract_hex_from_digest as _extract_hex_from_digest
from tasks.lib.digests import _fetch_digest_fallback as _fetch_digest_fallback
from tasks.lib.digests import _fetch_hashicorp_sha256 as _fetch_hashicorp_sha256
from tasks.lib.digests import _fetch_url_content as _fetch_url_content
from tasks.lib.digests import _parse_checksum_line as _parse_checksum_line
from tasks.lib.digests import _resolve_release_tag as _resolve_release_tag
from tasks.lib.digests import fetch_asset_digest as fetch_asset_digest
from tasks.lib.downloader import PackageDownloader as PackageDownloader
from tasks.lib.integrity import IntegrityError as IntegrityError
from tasks.lib.integrity import verify_file_sha256 as verify_file_sha256
from tasks.lib.metadata import METADATA_FILE as METADATA_FILE
from tasks.lib.metadata import METADATA_SCHEMA_FILE as METADATA_SCHEMA_FILE
from tasks.lib.metadata import ROOT_DIR as ROOT_DIR
from tasks.lib.metadata import MetadataCache as MetadataCache
from tasks.lib.metadata import load_metadata as load_metadata
from tasks.lib.platform import get_goarch as get_goarch
from tasks.lib.platform import get_os as get_os
from tasks.lib.platform import get_rust_arch as get_rust_arch
from tasks.lib.templates import (
    render_download_url_for_linux_amd64 as render_download_url_for_linux_amd64,
)
from tasks.lib.templates import render_template as render_template

_SEMVER_RE = re.compile(r"[vV]?(\d+\.\d+\.\d+(?:-[\w.-]+)?(?:\+[\w.-]+)?)")
_CALVER_RE = re.compile(r"[vV]?(\d{4}\.\d{1,2}\.\d{1,2}(?:\.\d+)?)")


def extract_semver_from_tag(tag: str) -> str | None:
    """Extract a semantic version string from a tag, stripping any 'v' prefix.

    Returns the version string if a valid semver is found, or None otherwise.
    """
    match = _SEMVER_RE.search(tag)
    if not match:
        return None
    candidate = match.group(1)
    try:
        semver.Version.parse(candidate)
    except ValueError:
        return None
    return candidate


def extract_calver_from_tag(tag: str) -> str | None:
    """Extract a CalVer (YYYY.MM.DD[.N]) version from a tag, stripping any 'v' prefix."""
    match = _CALVER_RE.search(tag)
    if not match:
        return None
    return match.group(1)


def extract_version_from_tag(tag: str) -> str | None:
    """Extract a semver or CalVer version string from a tag.

    Semver takes precedence; CalVer (e.g. 2026.08.29.2) is the fallback. The
    returned string preserves the tag's exact component formatting (including
    leading zeros) so it can be rendered back into download URLs.
    """
    return extract_semver_from_tag(tag) or extract_calver_from_tag(tag)


def compare_versions(left: str, right: str) -> int | None:
    """Compare two version strings (semver or CalVer).

    Returns -1, 0, or 1; None when the two cannot be compared. Strict semver
    semantics (including prerelease/build precedence) apply when both sides
    parse as semver; otherwise falls back to numeric comparison of
    dot-separated components, which handles CalVer's leading zeros
    (2026.08.10 > 2026.08.09).
    """

    def numeric_key(version: str) -> tuple[int, ...] | None:
        parts = version.strip().lstrip("vV").split(".")
        if not all(part.isdigit() and part for part in parts):
            return None
        return tuple(int(part) for part in parts)

    try:
        left_semver = semver.Version.parse(left)
        right_semver = semver.Version.parse(right)
    except ValueError:
        left_key = numeric_key(left)
        right_key = numeric_key(right)
        if left_key is None or right_key is None:
            return None
        if left_key < right_key:
            return -1
        if left_key > right_key:
            return 1
        return 0

    if left_semver < right_semver:
        return -1
    if left_semver > right_semver:
        return 1
    return 0


def _patch_invoke_fionread() -> None:
    """Make invoke's bytes_to_read safe on Python 3.14+.

    invoke 3.0.3 passes a 2-byte buffer to fcntl.ioctl(FIONREAD), which writes
    4 bytes. Python 3.14 detects the undersized buffer and raises SystemError
    (python/cpython#132915), killing invoke's stdin forwarding thread the first
    time a keystroke is pending while Context.run executes a subprocess.

    Upstream fix is still unreleased (pyinvoke/invoke#1070). Drop this patch
    once a released invoke > 3.0.3 fixes bytes_to_read.
    """
    import fcntl
    import struct
    import termios

    from invoke import runners, terminals
    from invoke.util import has_fileno, isatty

    def bytes_to_read(input_) -> int:
        if not terminals.WINDOWS and isatty(input_) and has_fileno(input_):
            buf = bytearray(4)
            fcntl.ioctl(input_, termios.FIONREAD, buf, True)
            return int(struct.unpack("i", buf)[0])
        return 1

    terminals.bytes_to_read = bytes_to_read
    runners.bytes_to_read = bytes_to_read


_patch_invoke_fionread()
