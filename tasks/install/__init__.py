import os
from pathlib import Path

from dotenv import load_dotenv
from invoke.context import Context
from invoke.tasks import task

from tasks.install.download import PackageDownloader
from tasks.lib import ROOT_DIR, load_metadata, render_template

load_dotenv()


INSTALL_PATH = os.getenv("INSTALL_PATH", "/usr/local/bin")


@task(aliases=["p"])
def package(
    c: Context,
    name: str,
    dist: bool = True,
    force: bool = False,
    install_path: str | None = None,
) -> None:
    """Install a single package (defaults to dist/ or INSTALL_PATH)."""
    metadata = load_metadata()
    package_metadata = metadata[name]

    download_url = render_template(name, package_metadata, package_metadata["download_url"])

    if dist:
        resolved_install_path = (Path(ROOT_DIR) / "dist").absolute()
    else:
        resolved_install_path = Path(install_path) if install_path else Path(INSTALL_PATH)

    if force:
        c.run(f"rm -rvf {resolved_install_path}/{name}")

    if (resolved_install_path / name).exists():
        print(f"{name} already installed")
    else:
        downloader = PackageDownloader(
            c,
            package_name=name,
            download_url=download_url,
            install_path=str(resolved_install_path),
            package_exe=package_metadata.get("package_exe", None),
            binary=package_metadata.get("binary", False),
        )

        downloader.download()


@task(aliases=["a", "all"])
def all_packages(c: Context, dist: bool = True, force: bool = False) -> None:
    """Install all packages (defaults to dist/ or INSTALL_PATH)."""
    metadata = load_metadata()
    for package_id in metadata:
        package(c, name=package_id, dist=dist, force=force)


@task
def local(c: Context, name: str, force: bool = False) -> None:
    """Install a package to ~/.local/bin if available, else ~/bin."""
    home = Path.home()
    local_bin = home / ".local" / "bin"
    fallback_bin = home / "bin"

    path_entries = [p for p in os.getenv("PATH", "").split(os.pathsep) if p]
    normalized_path_entries = {str(Path(p).resolve()) for p in path_entries}

    target = None
    if local_bin.exists() and str(local_bin.resolve()) in normalized_path_entries:
        target = local_bin
    else:
        target = fallback_bin

    if not target.exists():
        print(f"Creating {target}")
        target.mkdir(parents=True, exist_ok=True)

    print(f"Installing to {target}")

    package(
        c,
        name=name,
        dist=False,
        force=force,
        install_path=str(target),
    )


@task(aliases=["la"])
def local_all(c: Context, force: bool = False) -> None:
    """Install all packages to ~/.local/bin if available, else ~/bin."""
    metadata = load_metadata()
    for package_id in metadata:
        local(c, name=package_id, force=force)
