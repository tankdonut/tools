from invoke.context import Context
from invoke.tasks import task

from tasks.tools._install import install_single_package, resolve_install_path
from tasks.tools._metadata import metadata_cache


@task
def install(
    c: Context,
    name: str = "",
    local: bool = False,
    dist: bool = True,
    force: bool = False,
) -> None:
    """Install tools to dist or local."""
    install_path = resolve_install_path(local=local, dist=dist)

    if name:
        install_single_package(c, name, install_path, force=force)
    else:
        metadata = metadata_cache.get()
        for package_id in metadata:
            install_single_package(c, package_id, install_path, force=force)
        metadata_cache.clear()
