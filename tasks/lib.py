import hashlib
from pathlib import Path
import platform
import re
import subprocess
import tempfile
from typing import Any

from invoke.context import Context
from jinja2 import BaseLoader, Environment
import requests
import semver
import tenacity
import yaml

_SEMVER_RE = re.compile(r"[vV]?(\d+\.\d+\.\d+(?:-[\w.-]+)?(?:\+[\w.-]+)?)")

_os_cache: str | None = None


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


class MetadataCache:
    """Simple in-memory cache for metadata."""

    _instance = None
    _metadata: dict | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get(self) -> Any:
        """Get cached metadata or load it."""
        if self._metadata is None:
            self._metadata = load_metadata()
        return self._metadata

    def clear(self) -> None:
        """Clear cache."""
        self._metadata = None


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


def get_goarch():
    arch = platform.machine().lower()

    # Mapping common platform.machine() outputs to GOARCH values
    arch_map = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "i386": "386",
        "i686": "386",
        "x86": "386",
        "arm64": "arm64",
        "aarch64": "arm64",
        "armv7l": "arm",
        "armv6l": "arm",
        "ppc64le": "ppc64le",
        "ppc64": "ppc64",
        "mips": "mips",
        "mipsle": "mipsle",
        "mips64": "mips64",
        "mips64le": "mips64le",
        "s390x": "s390x",
    }

    goarch = arch_map.get(arch)
    if not goarch:
        raise ValueError(f"Unsupported architecture: {arch}")
    return goarch


def get_rust_arch():
    """
    Returns the system architecture string similar to Rust's arch naming.
    Examples: 'x86_64', 'aarch64', 'arm', 'i386', etc.
    """
    machine = platform.machine().lower()

    # Normalize common architecture names to Rust-like arch strings
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    elif machine in ("i386", "i686", "x86"):
        return "x86"
    elif machine.startswith("armv7") or machine == "arm":
        return "arm"
    elif machine.startswith("aarch64") or machine == "arm64":
        return "aarch64"
    elif machine.startswith("ppc64"):
        return "powerpc64"
    elif machine.startswith("ppc"):
        return "powerpc"
    else:
        return machine  # fallback to whatever platform.machine() returns


ROOT_DIR = Path(Path(__file__).parent / Path("..")).resolve()

METADATA_FILE = Path(Path(__file__).parent / Path("metadata.yaml")).absolute()
METADATA_SCHEMA_FILE = Path(METADATA_FILE).with_suffix(".schema.json")


def load_metadata() -> Any:
    with METADATA_FILE.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_os() -> str:
    global _os_cache
    if _os_cache is None:
        _os_cache = subprocess.check_output(["uname", "-s"], text=True).strip().lower()
    return _os_cache


def render_template(package_id: str, package_metadata: dict[str, Any], template_str: str) -> str:
    env = Environment(loader=BaseLoader())
    template = env.from_string(template_str)
    result = template.render(
        os=get_os(),
        arch=get_goarch(),
        rust_arch=get_rust_arch(),
        name=package_id,
        **package_metadata,
    )
    return result


class PackageDownloader:
    CURL = "curl --retry 3 --retry-delay 5 --fail -sSL"

    def __init__(
        self,
        ctx: Context,
        package_name: str,
        download_url: str,
        install_path: str,
        package_exe: str | None = None,
        binary: bool = False,
        sha256: str | None = None,
    ) -> None:
        self._ctx = ctx
        self._package_name = package_name
        self._download_url = download_url
        self._install_path = install_path
        self._binary = binary
        self._sha256 = sha256

        if package_exe:
            self._package_exe = package_exe
        else:
            self._package_exe = self._package_name

    def _curl(self, url: str, dest: str) -> None:
        print(f"downloading {url} to {dest}")
        self._ctx.run(f"{self.CURL} -o {dest} {url}")

    def _chmod(self, path: str) -> None:
        self._ctx.run(f"chmod -v +x {path}")

    def _mkdir(self, path: str) -> None:
        self._ctx.run(f"mkdir -vp -m a+rX {path}")

    def _verify(self, file_path: str) -> None:
        """Verify SHA256 checksum if configured."""
        verify_file_sha256(file_path, self._sha256, self._package_name)

    def _install(self, src: str, dest: str) -> None:
        self._ctx.run(f"install -v {src} {dest}")

    def download(self) -> None:
        if self._download_url.endswith(".bgz") and self._binary:
            self.download_binary_gz()
        elif self._download_url.endswith(".tar.bz2"):
            self.download_tar_bz2()
        elif self._download_url.endswith(".bz2") and self._binary:
            self.download_binary_bz2()
        elif self._download_url.endswith(".tar.gz"):
            self.download_tar_gz()
        elif self._download_url.endswith(".tar.xz"):
            self.download_tar_xz()
        elif self._download_url.endswith(".tar"):
            self.download_tarball()
        elif self._download_url.endswith(".gz"):
            self.download_gz()
        elif self._download_url.endswith(".zip"):
            self.download_zip()
        else:
            self.download_binary()

    def download_binary(self) -> None:
        self._mkdir(self._install_path)
        dest = f"{self._install_path}/{self._package_exe}"
        self._curl(self._download_url, dest)
        self._verify(dest)
        self._chmod(dest)

    def download_binary_gz(self) -> None:
        self._mkdir(self._install_path)
        gz_path = f"{self._install_path}/{self._package_name}.gz"
        self._curl(self._download_url, gz_path)
        self._verify(gz_path)
        self._ctx.run(f"gunzip -f -k -q {gz_path}")
        self._chmod(f"{self._install_path}/{self._package_exe}")
        self._ctx.run(f"rm -rf {gz_path}")

    def download_binary_bz2(self) -> None:
        self._mkdir(self._install_path)
        bz2_path = f"{self._install_path}/{self._package_name}.bz2"
        self._curl(self._download_url, bz2_path)
        self._verify(bz2_path)
        self._ctx.run(f"bzip2 -d -f -k -q {bz2_path}")
        self._chmod(f"{self._install_path}/{self._package_exe}")
        self._ctx.run(f"rm -rf {bz2_path}")

    def download_tarball(self) -> None:
        self._mkdir(self._install_path)
        with tempfile.TemporaryDirectory(suffix=self._package_name) as temp_dir:
            archive_path = f"{temp_dir}/{self._package_name}.tar.gz"
            self._curl(self._download_url, archive_path)
            self._verify(archive_path)
            self._ctx.run(f"tar -zx -C {temp_dir} -f {archive_path}")
            self._ctx.run(
                f"find {temp_dir} -type f -name '{self._package_name}*' | \
                    xargs -I {{}} cp -f {{}} {self._install_path}/{self._package_exe}"
            )
            self._chmod(f"{self._install_path}/{self._package_exe}")

    def download_tar_bz2(self) -> None:
        self._mkdir(self._install_path)
        with tempfile.TemporaryDirectory(suffix=self._package_name) as temp_dir:
            archive_path = f"{temp_dir}/{self._package_name}.tar.bz2"
            self._curl(self._download_url, archive_path)
            self._verify(archive_path)
            self._ctx.run(f"tar -jx -C {temp_dir} -f {archive_path}")
            self._ctx.run(
                f"find {temp_dir} -type f -name {self._package_name} | \
                    xargs -I {{}} cp -f {{}} {self._install_path}/{self._package_exe}"
            )
            self._chmod(f"{self._install_path}/{self._package_exe}")

    def download_tar_gz(self) -> None:
        self._mkdir(self._install_path)
        with tempfile.TemporaryDirectory(suffix=self._package_name) as temp_dir:
            archive_path = f"{temp_dir}/{self._package_name}.tar.gz"
            self._curl(self._download_url, archive_path)
            self._verify(archive_path)
            self._ctx.run(f"tar -zx -C {temp_dir} -f {archive_path}")
            self._ctx.run(
                f"find {temp_dir} -type f -name {self._package_name} | \
                    xargs -I {{}} cp -f {{}} {self._install_path}/{self._package_exe}"
            )
            self._chmod(f"{self._install_path}/{self._package_exe}")

    def download_tar_xz(self) -> None:
        self._mkdir(self._install_path)
        with tempfile.TemporaryDirectory(suffix=self._package_name) as temp_dir:
            archive_path = f"{temp_dir}/{self._package_name}.tar.xz"
            self._curl(self._download_url, archive_path)
            self._verify(archive_path)
            self._ctx.run(f"tar -Jx -C {temp_dir} -f {archive_path}")
            self._ctx.run(
                f"find {temp_dir} -type f -name {self._package_name} | \
                    xargs -I {{}} cp -f {{}} {self._install_path}/{self._package_exe}"
            )
            self._chmod(f"{self._install_path}/{self._package_exe}")

    def download_zip(self) -> None:
        self._mkdir(self._install_path)
        with tempfile.TemporaryDirectory(suffix=self._package_name) as temp_dir:
            zip_path = f"{temp_dir}/{self._package_name}.zip"
            self._curl(self._download_url, zip_path)
            self._verify(zip_path)
            self._ctx.run(f"unzip {zip_path} -d {temp_dir}")
            self._ctx.run(
                f"find {temp_dir} -type f -name {self._package_name} | \
                    xargs -I {{}} cp -f {{}} {self._install_path}/{self._package_exe}"
            )
            self._chmod(f"{self._install_path}/{self._package_exe}")

    def download_gz(self) -> None:
        self._mkdir(self._install_path)
        with tempfile.TemporaryDirectory(suffix=self._package_name) as temp_dir:
            gz_path = f"{temp_dir}/{self._package_name}.gz"
            self._curl(self._download_url, gz_path)
            self._verify(gz_path)
            self._ctx.run(f"gunzip {gz_path}")
            self._ctx.run(
                f"find {temp_dir} -type f -name {self._package_name} | \
                    xargs -I {{}} cp -f {{}} {self._install_path}/{self._package_exe}"
            )
            self._chmod(f"{self._install_path}/{self._package_exe}")


def render_download_url_for_linux_amd64(package_id: str, package_metadata: dict[str, Any]) -> str:
    """Render the download_url template for linux/amd64."""
    env = Environment(loader=BaseLoader())
    template = env.from_string(package_metadata["download_url"])
    render_kwargs: dict[str, Any] = {
        "os": "linux",
        "arch": "amd64",
        "rust_arch": "x86_64",
        "name": package_id,
    }
    for key, value in package_metadata.items():
        if key not in render_kwargs:
            render_kwargs[key] = value
    return template.render(**render_kwargs)


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

        escaped = asset_filename.replace(".", "\\\\.").replace("+", "\\\\+")
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
