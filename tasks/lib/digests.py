from pathlib import Path
import re
import subprocess
from typing import Any

from jinja2 import BaseLoader, Environment
import requests
import tenacity

# Digest fallback map: tool name -> (digest_file_pattern, format_type)
# format_type: "standard" = "<hash>  <filename>"
#              "dist_prefix" = "<hash>  _dist/<filename>"
#              "bare" = "<hash>" (no filename on the line)
DIGEST_FALLBACK: dict[str, tuple[str, str]] = {
    "argocd": ("cli_checksums.txt", "standard"),
    "bd": ("checksums.txt", "standard"),
    "cr": ("checksums.txt", "standard"),
    "ct": ("checksums.txt", "standard"),
    "ctlptl": ("checksums.txt", "standard"),
    "doctl": ("doctl-{version}-checksums.sha256", "standard"),
    "exo": ("exoscale-cli_{version}_checksums.txt", "standard"),
    "flux": ("flux_{version}_checksums.txt", "standard"),
    "helm-docs": ("checksums.txt", "standard"),
    "k3d": ("checksums.txt", "dist_prefix"),
    "k3s": ("sha256sum-amd64.txt", "standard"),
    "k9s": ("checksums.sha256", "standard"),
    "kind": ("{name}-{os}-{arch}.sha256sum", "bare"),
    "kustomize": ("checksums.txt", "standard"),
    "minikube": ("{name}-{os}-{arch}.sha256", "bare"),
    "rtk": ("checksums.txt", "standard"),
    "skaffold": ("{name}-{os}-{arch}.sha256", "bare"),
    "starship": ("{asset}.sha256", "bare"),
    "terraform-docs": ("terraform-docs-v{version}.sha256sum", "standard"),
    "terragrunt": ("SHA256SUMS", "standard"),
    "tflint": ("checksums.txt", "standard"),
    "tilt": ("checksums.txt", "standard"),
}


def _resolve_release_tag(
    owner: str,
    repo: str,
    version: str,
    download_url_template: str = "",
) -> str | None:
    """Try common tag formats to find the release for a given version.

    Tries: v{version}, kustomize/v{version}, {version}, and if a
    download_url_template is provided, extracts the tag pattern from
    ``/releases/download/{tag}/`` and renders it with the version.
    """
    tag_candidates = [
        f"v{version}",
        f"kustomize/v{version}",
        version,
    ]

    if download_url_template:
        tag_match = re.search(r"/releases/download/([^/]+)/", download_url_template)
        if tag_match:
            raw_tag = tag_match.group(1)
            env = Environment(loader=BaseLoader())
            try:
                rendered_tag = env.from_string(raw_tag).render(version=version)
            except Exception:
                rendered_tag = raw_tag
            if rendered_tag not in tag_candidates:
                tag_candidates.append(rendered_tag)

    for tag in tag_candidates:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{owner}/{repo}/releases/tags/{tag}",
                "--jq",
                ".tag_name",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return tag
    return None


def _extract_hex_from_digest(digest_value: str) -> str | None:
    """Extract the hex portion from a digest field value like 'sha256:<hex>'."""
    if not digest_value or not digest_value.strip():
        return None
    val = digest_value.strip()
    if val.startswith("sha256:"):
        return val[len("sha256:") :]

    if all(c in "0123456789abcdef" for c in val.lower()) and len(val) == 64:
        return val.lower()
    return None


@tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
    retry=tenacity.retry_if_exception_type(requests.exceptions.Timeout),
)
def _fetch_url_content(url: str) -> str | None:
    """Fetch text content from a URL with retry."""
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            return response.text
    except requests.exceptions.Timeout:
        raise
    except Exception:
        pass
    return None


def _parse_checksum_line(content: str, filename: str, fmt: str) -> str | None:
    """Parse a checksum file to find the hash for a given filename.

    fmt: "standard" -> "<hash>  <filename>"
         "dist_prefix" -> "<hash>  _dist/<filename>"
         "bare" -> "<hash>" (entire line is just the hash)
    """
    for line in content.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        if fmt == "bare":
            # Bare hash: entire non-empty line is the hash
            if all(c in "0123456789abcdef" for c in line.lower()) and len(line) == 64:
                return line.lower()
            continue

        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        hash_val, fname = parts[0], parts[1].strip()

        if fmt == "dist_prefix":
            # Match _dist/<filename>
            if fname == f"_dist/{filename}" or fname == f"_dist/{Path(filename).name}":
                return hash_val.lower()
        elif fmt == "standard" and (fname == filename or fname == Path(filename).name):
            return hash_val.lower()

    return None


def _fetch_hashicorp_sha256(name: str, version: str) -> str | None:
    """Fetch SHA256 from HashiCorp releases site for packer/terraform."""
    url = f"https://releases.hashicorp.com/{name}/{version}/{name}_{version}_SHA256SUMS"
    content = _fetch_url_content(url)
    if not content:
        return None
    target = f"{name}_{version}_linux_amd64.zip"
    for line in content.strip().splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip() == target:
            return parts[0].lower()
    return None


def _fetch_digest_fallback(
    owner: str,
    repo: str,
    version: str,
    asset_filename: str,
    tool_name: str,
    package_metadata: dict[str, Any],
) -> str | None:
    """Try to fetch digest from checksum files when API digest is null."""
    if tool_name not in DIGEST_FALLBACK:
        return None

    digest_file_pattern, fmt = DIGEST_FALLBACK[tool_name]

    env = Environment(loader=BaseLoader())
    template = env.from_string(digest_file_pattern)
    render_kwargs: dict[str, Any] = {
        "os": "linux",
        "arch": "amd64",
        "rust_arch": "x86_64",
        "name": tool_name,
        "version": version,
        "asset": asset_filename,
    }
    for key, value in package_metadata.items():
        if key not in render_kwargs:
            render_kwargs[key] = value
    digest_file = template.render(**render_kwargs)

    tag = _resolve_release_tag(owner, repo, version, package_metadata.get("download_url", ""))
    if not tag:
        return None

    base_url = f"https://github.com/{owner}/{repo}/releases/download/{tag}"
    checksum_url = f"{base_url}/{digest_file}"

    content = _fetch_url_content(checksum_url)
    if not content:
        return None

    return _parse_checksum_line(content, asset_filename, fmt)


def fetch_asset_digest(
    owner: str,
    repo: str,
    version: str,
    asset_filename: str,
    tool_name: str = "",
    package_metadata: dict[str, Any] | None = None,
) -> str | None:
    """Fetch SHA256 digest for a GitHub release asset.

    1. Query GitHub Release API for the asset's digest field
    2. If null, fall back to fetching known digest files
    3. For HashiCorp tools, use releases.hashicorp.com

    Returns the SHA256 hex string, or None if not found.
    """
    package_metadata = package_metadata or {}
    download_url_template = package_metadata.get("download_url", "")

    if tool_name in ("packer", "terraform"):
        return _fetch_hashicorp_sha256(tool_name, version)

    if tool_name == "asdf":
        return None

    tag = _resolve_release_tag(owner, repo, version, download_url_template)
    if tag:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{owner}/{repo}/releases/tags/{tag}",
                "--jq",
                f'.assets[] | select(.name == "{asset_filename}") | .digest',
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            digest = _extract_hex_from_digest(result.stdout.strip())
            if digest:
                return digest

        escaped = asset_filename.replace(".", "\\.").replace("+", "\\+")
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{owner}/{repo}/releases/tags/{tag}",
                "--jq",
                f'.assets[] | select(.name | test("^{escaped}$"; "i")) | .digest',
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            digest = _extract_hex_from_digest(result.stdout.strip())
            if digest:
                return digest

    return _fetch_digest_fallback(owner, repo, version, asset_filename, tool_name, package_metadata)
