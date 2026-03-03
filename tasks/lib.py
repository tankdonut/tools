from pathlib import Path
import platform
import subprocess
import tempfile
from typing import Any

from invoke.context import Context
from jinja2 import BaseLoader, Environment
import yaml

_os_cache: str | None = None


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
    ) -> None:
        self._ctx = ctx
        self._package_name = package_name
        self._download_url = download_url
        self._install_path = install_path
        self._binary = binary

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
        self._curl(self._download_url, f"{self._install_path}/{self._package_exe}")
        self._chmod(f"{self._install_path}/{self._package_exe}")

    def download_binary_gz(self) -> None:
        self._mkdir(self._install_path)
        self._curl(
            self._download_url,
            f"{self._install_path}/{self._package_name}.gz",
        )
        self._ctx.run(f"gunzip -f -k -q {self._install_path}/{self._package_name}.gz")
        self._chmod(f"{self._install_path}/{self._package_exe}")
        self._ctx.run(f"rm -rf {self._install_path}/{self._package_name}.gz")

    def download_binary_bz2(self) -> None:
        self._mkdir(self._install_path)
        self._curl(self._download_url, f"{self._install_path}/{self._package_name}.bz2")
        self._ctx.run(f"bzip2 -d -f -k -q {self._install_path}/{self._package_name}.bz2")
        self._chmod(f"{self._install_path}/{self._package_exe}")
        self._ctx.run(f"rm -rf {self._install_path}/{self._package_name}.bz2")

    def download_tarball(self) -> None:
        self._mkdir(self._install_path)
        with tempfile.TemporaryDirectory(suffix=self._package_name) as temp_dir:
            self._ctx.run(f"{self.CURL} -o - {self._download_url} | tar -zx -C {temp_dir}")
            self._ctx.run(
                f"find {temp_dir} -type f -name '{self._package_name}*' | \
                    xargs -I {{}} cp -f {{}} {self._install_path}/{self._package_exe}"
            )
            self._chmod(f"{self._install_path}/{self._package_exe}")

    def download_tar_bz2(self) -> None:
        self._mkdir(self._install_path)
        with tempfile.TemporaryDirectory(suffix=self._package_name) as temp_dir:
            self._ctx.run(f"{self.CURL} -o - {self._download_url} | tar -jx -C {temp_dir}")
            self._ctx.run(
                f"find {temp_dir} -type f -name {self._package_name} | \
                    xargs -I {{}} cp -f {{}} {self._install_path}/{self._package_exe}"
            )
            self._chmod(f"{self._install_path}/{self._package_exe}")

    def download_tar_gz(self) -> None:
        self._mkdir(self._install_path)
        with tempfile.TemporaryDirectory(suffix=self._package_name) as temp_dir:
            self._ctx.run(f"{self.CURL} -o - {self._download_url} | tar -zx -C {temp_dir}")
            self._ctx.run(
                f"find {temp_dir} -type f -name {self._package_name} | \
                    xargs -I {{}} cp -f {{}} {self._install_path}/{self._package_exe}"
            )
            self._chmod(f"{self._install_path}/{self._package_exe}")

    def download_tar_xz(self) -> None:
        self._mkdir(self._install_path)
        with tempfile.TemporaryDirectory(suffix=self._package_name) as temp_dir:
            self._ctx.run(f"{self.CURL} -o - {self._download_url} | tar -Jx -C {temp_dir}")
            self._ctx.run(
                f"find {temp_dir} -type f -name {self._package_name} | \
                    xargs -I {{}} cp -f {{}} {self._install_path}/{self._package_exe}"
            )
            self._chmod(f"{self._install_path}/{self._package_exe}")

    def download_zip(self) -> None:
        self._mkdir(self._install_path)
        with tempfile.TemporaryDirectory(suffix=self._package_name) as temp_dir:
            self._curl(self._download_url, f"{temp_dir}/{self._package_name}.zip")
            self._ctx.run(f"unzip {temp_dir}/{self._package_name}.zip -d {temp_dir}")
            self._ctx.run(
                f"find {temp_dir} -type f -name {self._package_name} | \
                    xargs -I {{}} cp -f {{}} {self._install_path}/{self._package_exe}"
            )
            self._chmod(f"{self._install_path}/{self._package_exe}")

    def download_gz(self) -> None:
        self._mkdir(self._install_path)
        with tempfile.TemporaryDirectory(suffix=self._package_name) as temp_dir:
            self._curl(self._download_url, f"{temp_dir}/{self._package_name}.gz")
            self._ctx.run(f"gunzip {temp_dir}/{self._package_name}.gz")
            self._ctx.run(
                f"find {temp_dir} -type f -name {self._package_name} | \
                    xargs -I {{}} cp -f {{}} {self._install_path}/{self._package_exe}"
            )
            self._chmod(f"{self._install_path}/{self._package_exe}")
