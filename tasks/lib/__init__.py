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
