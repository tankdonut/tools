import logging

from invoke.context import Context
from invoke.exceptions import Exit
from invoke.tasks import task
from rich.console import Console

from tasks.tools._install import install_single_package, resolve_install_path
from tasks.tools._metadata import metadata_cache

console = Console()


@task
def install(
    c: Context,
    name: str = "",
    local: bool = False,
    dist: bool = True,
    force: bool = False,
    verbose: bool = False,
) -> None:
    """Install tools to dist or local.

    Use --verbose to echo the underlying shell commands (curl, tar, etc.) and
    show download progress.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    install_path = resolve_install_path(local=local, dist=dist)

    if name:
        install_single_package(c, name, install_path, force=force, verbose=verbose)
        return

    metadata = metadata_cache.get()
    total = len(metadata)
    failed: list[str] = []

    try:
        for index, package_id in enumerate(metadata, start=1):
            console.print(f"[bold]\\[{index}/{total}][/bold] installing {package_id}")
            try:
                install_single_package(c, package_id, install_path, force=force, verbose=verbose)
            except Exception as e:
                console.print(f"  [red]✗[/red] {package_id}: {e}")
                failed.append(package_id)
    finally:
        metadata_cache.clear()

    console.print()
    succeeded = total - len(failed)
    console.print(
        f"[bold]Summary[/bold]: [green]{succeeded} installed[/green], "
        f"[red]{len(failed)} failed[/red]"
    )
    if failed:
        console.print(f"[red]Failed:[/red] {', '.join(failed)}")
        raise Exit(1)
