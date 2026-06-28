import logging
import tempfile

from invoke.context import Context

from tasks.lib.integrity import verify_file_sha256

logger = logging.getLogger(__name__)


class PackageDownloader:
    CURL = "curl --retry 3 --retry-delay 5 --fail -sSL"
    CURL_VERBOSE = "curl --retry 3 --retry-delay 5 --fail -SL"

    def __init__(
        self,
        ctx: Context,
        package_name: str,
        download_url: str,
        install_path: str,
        package_exe: str | None = None,
        binary: bool = False,
        sha256: str | None = None,
        verbose: bool = False,
    ) -> None:
        self._ctx = ctx
        self._package_name = package_name
        self._download_url = download_url
        self._install_path = install_path
        self._binary = binary
        self._sha256 = sha256
        self._verbose = verbose

        if package_exe:
            self._package_exe = package_exe
        else:
            self._package_exe = self._package_name

    def _run(self, command: str) -> None:
        """Run a shell command via the invoke context, echoing when verbose."""
        self._ctx.run(command, echo=self._verbose)

    def _curl(self, url: str, dest: str) -> None:
        logger.info("downloading %s from %s", self._package_name, url)
        curl = self.CURL_VERBOSE if self._verbose else self.CURL
        self._run(f"{curl} -o {dest} {url}")

    def _chmod(self, path: str) -> None:
        self._run(f"chmod -v +x {path}")

    def _mkdir(self, path: str) -> None:
        self._run(f"mkdir -vp -m a+rX {path}")

    def _verify(self, file_path: str) -> None:
        """Verify SHA256 checksum if configured."""
        if self._sha256:
            logger.info("verifying SHA256 for %s", self._package_name)
            verify_file_sha256(file_path, self._sha256, self._package_name)
        else:
            logger.warning("no sha256 digest for %s, skipping verification", self._package_name)

    def _install(self, src: str, dest: str) -> None:
        self._run(f"install -v {src} {dest}")

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
        self._run(f"gunzip -f -k -q {gz_path}")
        self._chmod(f"{self._install_path}/{self._package_exe}")
        self._run(f"rm -rf {gz_path}")

    def download_binary_bz2(self) -> None:
        self._mkdir(self._install_path)
        bz2_path = f"{self._install_path}/{self._package_name}.bz2"
        self._curl(self._download_url, bz2_path)
        self._verify(bz2_path)
        self._run(f"bzip2 -d -f -k -q {bz2_path}")
        self._chmod(f"{self._install_path}/{self._package_exe}")
        self._run(f"rm -rf {bz2_path}")

    def download_tarball(self) -> None:
        self._mkdir(self._install_path)
        with tempfile.TemporaryDirectory(suffix=self._package_name) as temp_dir:
            archive_path = f"{temp_dir}/{self._package_name}.tar.gz"
            self._curl(self._download_url, archive_path)
            self._verify(archive_path)
            self._run(f"tar -zx -C {temp_dir} -f {archive_path}")
            self._run(
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
            self._run(f"tar -jx -C {temp_dir} -f {archive_path}")
            self._run(
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
            self._run(f"tar -zx -C {temp_dir} -f {archive_path}")
            self._run(
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
            self._run(f"tar -Jx -C {temp_dir} -f {archive_path}")
            self._run(
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
            self._run(f"unzip {zip_path} -d {temp_dir}")
            self._run(
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
            self._run(f"gunzip {gz_path}")
            self._run(
                f"find {temp_dir} -type f -name {self._package_name} | \
                    xargs -I {{}} cp -f {{}} {self._install_path}/{self._package_exe}"
            )
            self._chmod(f"{self._install_path}/{self._package_exe}")
