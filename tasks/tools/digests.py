from invoke.tasks import task
from rich.console import Console

from tasks.lib import fetch_asset_digest, render_download_url_for_linux_amd64
from tasks.tools._github import get_owner_and_repo
from tasks.tools._metadata import metadata_cache, write_metadata


@task
def digests(
    c,
    name: str = "",
) -> None:
    """Fetch SHA256 digests for all tools and write to metadata.yaml."""
    console = Console()
    metadata = metadata_cache.get()

    if name:
        if name not in metadata:
            console.print(f"[red]Tool '{name}' not found in metadata[/red]")
            return
        tools_to_process = {name: metadata[name]}
    else:
        tools_to_process = metadata

    updated = False

    for tool_name, pkg_meta in tools_to_process.items():
        version = pkg_meta.get("version")
        repo_url = pkg_meta.get("repo_url")

        if not version or not repo_url:
            console.print(f"  [yellow]SKIP[/yellow] {tool_name}: missing version or repo_url")
            continue

        if tool_name == "asdf":
            console.print(
                f"  [yellow]SKIP[/yellow] {tool_name}: only MD5 digests available, not SHA256"
            )
            continue

        owner, repo = get_owner_and_repo(repo_url)
        if not owner or not repo:
            console.print(f"  [yellow]SKIP[/yellow] {tool_name}: cannot parse owner/repo")
            continue

        resolved_url = render_download_url_for_linux_amd64(tool_name, pkg_meta)
        asset_filename = resolved_url.rsplit("/", 1)[-1] if "/" in resolved_url else resolved_url

        sha256 = fetch_asset_digest(
            owner=owner,
            repo=repo,
            version=version,
            asset_filename=asset_filename,
            tool_name=tool_name,
            package_metadata=pkg_meta,
        )

        if sha256:
            pkg_meta["sha256"] = sha256
            updated = True
            console.print(f"  [green]OK[/green] {tool_name}: {sha256[:16]}...")
        else:
            console.print(f"  [red]MISSING[/red] {tool_name}: digest not found")

    if updated:
        write_metadata(metadata)
        metadata_cache.clear()
        console.print("\n[bold green]Metadata updated with sha256 digests.[/bold green]")
    else:
        console.print("\n[yellow]No digests found.[/yellow]")
