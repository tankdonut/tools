import os
from pathlib import Path
import shutil

from invoke.context import Context
from rich.console import Console

from tasks.lib import ROOT_DIR, IntegrityError, PackageDownloader, render_template
from tasks.tools._metadata import metadata_cache

console = Console()


def check_required_tools(download_url: str, package_name: str = "") -> None:
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
            suffix = f" (required for '{package_name}')" if package_name else ""
            raise RuntimeError(f"Required tool '{tool}' not found in PATH{suffix}")


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
    verbose: bool = False,
) -> None:
    """Install a single tool."""
    metadata = metadata_cache.get()

    if name not in metadata:
        raise ValueError(f"Tool '{name}' not found in metadata")

    package_metadata = metadata[name]
    download_url = render_template(name, package_metadata, package_metadata["download_url"])

    check_required_tools(download_url, package_name=name)

    if force and (install_path / name).exists():
        shutil.rmtree(install_path / name)

    if (install_path / name).exists():
        console.print(f"  [yellow]SKIP[/yellow] {name}: already installed at {install_path}")
        return

    if not install_path.exists():
        install_path.mkdir(parents=True, exist_ok=True)

    downloader = PackageDownloader(
        c,
        package_name=name,
        download_url=download_url,
        install_path=str(install_path),
        package_exe=package_metadata.get("package_exe", None),
        binary=package_metadata.get("binary", False),
        sha256=package_metadata.get("sha256"),
        verbose=verbose,
    )

    try:
        downloader.download()
    except IntegrityError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to install '{name}' from {download_url}: {e}") from e

    console.print(f"  [green]OK[/green] {name}")
