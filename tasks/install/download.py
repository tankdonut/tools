import tempfile

from invoke import Context


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
