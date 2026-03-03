import os
from pathlib import Path
import shutil

from dotenv import load_dotenv
from invoke.context import Context
from invoke.tasks import task

from tasks.lib import ROOT_DIR, MetadataCache, PackageDownloader, render_template

metadata_cache = MetadataCache()

load_dotenv()


def check_required_tools(download_url: str) -> None:
    """Check for required command line tools."""
    required = {"curl"}

    if download_url.endswith(".zip"):
        required.add("unzip")
    elif download_url.endswith((".tar", ".tar.gz", ".tar.bz2", ".tar.xz")):
        required.add("tar")
    elif download_url.endswith((".gz", ".bz2")):
        required.add("gunzip")

    for tool in required:
        if not shutil.which(tool):
            raise RuntimeError(f"Required tool '{tool}' not found in PATH")


def resolve_install_path(local: bool = False, dist: bool = True) -> Path:
    """Resolve install path based on flags."""
    if local:
        home = Path.home()
        local_bin = home / ".local" / "bin"
        fallback_bin = home / "bin"

        path_entries = [p for p in os.getenv("PATH", "").split(os.pathsep) if p]
        normalized_path_entries = {str(Path(p).resolve()) for p in path_entries}

        if local_bin.exists() and str(local_bin.resolve()) in normalized_path_entries:
            return local_bin
        else:
            return fallback_bin

    if dist:
        return ROOT_DIR / "dist"

    raise ValueError("Either --local or --dist must be specified")


def install_single_package(
    c: Context,
    name: str,
    install_path: Path,
    force: bool = False,
) -> None:
    """Install a single package."""
    metadata = metadata_cache.get()

    if name not in metadata:
        raise ValueError(f"Package '{name}' not found in metadata")

    package_metadata = metadata[name]
    download_url = render_template(name, package_metadata, package_metadata["download_url"])

    check_required_tools(download_url)

    if force and (install_path / name).exists():
        c.run(f"rm -rvf {install_path}/{name}")

    if (install_path / name).exists():
        print(f"{name} already installed at {install_path}")
    else:
        if not install_path.exists():
            install_path.mkdir(parents=True, exist_ok=True)

        downloader = PackageDownloader(
            c,
            package_name=name,
            download_url=download_url,
            install_path=str(install_path),
            package_exe=package_metadata.get("package_exe", None),
            binary=package_metadata.get("binary", False),
        )

        downloader.download()


@task
def install(
    c: Context,
    name: str = "",
    local: bool = False,
    dist: bool = True,
    force: bool = False,
) -> None:
    """Install packages to dist or local."""
    install_path = resolve_install_path(local=local, dist=dist)

    if name:
        install_single_package(c, name, install_path, force=force)
    else:
        metadata = metadata_cache.get()
        for package_id in metadata:
            install_single_package(c, package_id, install_path, force=force)
        metadata_cache.clear()
