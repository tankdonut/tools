from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import subprocess
import tempfile

from invoke.tasks import task
from rich.console import Console

from tasks.lib import METADATA_FILE
from tasks.tools._automation import AutomationError, ensure_clean_checkout, safe_git_command
from tasks.tools._metadata import metadata_cache, write_metadata
from tasks.tools._updates import (
    RELEASE_AGE_DAYS,
    _format_checked_versions,
    _update_sha256_for_updates,
    detect_updates,
)

logger = logging.getLogger(__name__)


@task
def update(
    c,
    name: str = "",
    pr: bool = False,
    dry_run: bool = False,
    cooldown: int = RELEASE_AGE_DAYS,
) -> None:
    """Check and update tools. Use --name for single tool, --pr for PR automation."""
    console = Console()
    metadata = metadata_cache.get()

    if name:
        if name not in metadata:
            return
        check_data = {name: metadata[name]}
    else:
        check_data = metadata

    updates, skipped = detect_updates(check_data, cooldown=cooldown)

    if pr:
        if not updates and not skipped:
            console.print("No updates found.")
            return

        if not updates:
            console.print("No updates found, but some releases were skipped:")
            for s in skipped:
                chain_str = ""
                if "checked_versions" in s:
                    chain_str = f" (walked: {_format_checked_versions(s['checked_versions'])})"
                console.print(
                    f"  [yellow]⏭[/yellow] {s['package']}: {s['current_version']} → "
                    f"{s['skipped_version']} ({s['reason']}){chain_str}"
                )
            return

        branch_name = f"automation/update-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"

        if dry_run:
            console.print("[bold]Dry run mode enabled.[/bold]")
            console.print(f"Would create branch: [cyan]{branch_name}[/cyan]")
            console.print("Would commit: [cyan]chore: update tools[/cyan]")
            console.print(
                f"Would create PR targeting [cyan]'main'[/cyan] with {len(updates)} update(s)."
            )
            return

        with ensure_clean_checkout():
            for u in updates:
                metadata[u["package"]]["version"] = u["to_version"]

            sha_map = _update_sha256_for_updates(metadata, updates)

            for u in updates:
                pkg = u["package"]
                sha = sha_map.get(pkg)
                sha_str = (
                    f"  [dim]sha256: {sha[:16]}...[/dim]"
                    if sha
                    else "  [yellow]sha256: not found[/yellow]"
                )
                console.print(
                    f"  [green]✓[/green] {pkg}: {u['from_version']} → {u['to_version']}{sha_str}"
                )
                if "checked_versions" in u:
                    chain = _format_checked_versions(u["checked_versions"])
                    console.print(f"    walked: {chain}")

            write_metadata(metadata)
            metadata_cache.clear()

            # Checkout existing branch or create a new one
            branch_exists = safe_git_command("branch", "--list", branch_name).stdout.strip()

            if branch_exists:
                safe_git_command("checkout", branch_name)
            else:
                safe_git_command("checkout", "-b", branch_name)

            safe_git_command("add", str(METADATA_FILE))
            safe_git_command("commit", "-m", "chore: update tools")
            safe_git_command("push", "-u", "origin", branch_name)

            count = len(updates)

            if count <= 3:
                parts = [
                    f"{u['package']} ({u['from_version']} → {u['to_version']})" for u in updates
                ]
                title = f"chore: update {', '.join(parts)}"
            else:
                first = ", ".join(u["package"] for u in updates[:3])
                title = f"chore: update {first} +{count - 3} more"

            table_lines = [
                "| Package | From | To | SHA256 |",
                "|---|---|---|---|",
            ]
            for u in updates:
                pkg = u["package"]
                sha = metadata[pkg].get("sha256")
                sha_display = f"{sha[:16]}..." if sha else "N/A"
                table_lines.append(
                    f"| {pkg} | {u['from_version']} | {u['to_version']} | `{sha_display}` |"
                )

            update_table = "\n".join(table_lines)

            body = (
                "Automated weekly package updates.\n\n"
                f"{count} package(s) updated.\n\n"
                "<details>\n"
                "<summary>Updated Packages (click to expand)</summary>\n\n"
                f"{update_table}\n\n"
                "</details>"
            )

            if skipped:
                skip_lines = [
                    "| Package | Current | Skipped | Reason | Checked Versions |",
                    "|---|---|---|---|---|",
                ]
                for s in skipped:
                    chain = _format_checked_versions(s.get("checked_versions", []))
                    skip_lines.append(
                        f"| {s['package']} | {s['current_version']} "
                        f"| {s['skipped_version']} | {s['reason']} | {chain} |"
                    )
                skip_table = "\n".join(skip_lines)
                body += (
                    "\n\n<details>\n"
                    "<summary>Skipped Releases (click to expand)</summary>\n\n"
                    f"{skip_table}\n\n"
                    "</details>"
                )

            # Check for existing open PR
            try:
                pr_check = subprocess.run(
                    [
                        "gh",
                        "pr",
                        "list",
                        "--head",
                        branch_name,
                        "--state",
                        "open",
                        "--json",
                        "number,url",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                raise AutomationError(
                    f"Failed to check for existing PRs: {e.stderr.strip()}"
                ) from e

            existing_prs = json.loads(pr_check.stdout) if pr_check.stdout.strip() else []

            if existing_prs:
                pr_number = str(existing_prs[0]["number"])
                console.print(f"Reusing existing PR: [cyan]{existing_prs[0]['url']}[/cyan]")
            else:
                # Write body to temp file to avoid CLI argument length limits
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".md", delete=False, encoding="utf-8"
                ) as body_file:
                    body_file.write(body)
                    body_path = body_file.name

                try:
                    pr_create = subprocess.run(
                        [
                            "gh",
                            "pr",
                            "create",
                            "--title",
                            title,
                            "--body-file",
                            body_path,
                            "--head",
                            branch_name,
                            "--base",
                            "main",
                        ],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                except subprocess.CalledProcessError as e:
                    raise AutomationError(f"Failed to create PR: {e.stderr.strip()}") from e
                finally:
                    Path(body_path).unlink(missing_ok=True)
                pr_url = pr_create.stdout.strip()
                pr_number = pr_url.rstrip("/").rsplit("/", 1)[-1]
                console.print(f"Created PR: [cyan]{pr_url}[/cyan]")

            label_result = subprocess.run(
                ["gh", "pr", "edit", pr_number, "--add-label", "dependencies"],
                capture_output=True,
                text=True,
                check=False,
            )
            if label_result.returncode != 0:
                console.print(
                    f"  [yellow]⚠[/yellow] Failed to add label: {label_result.stderr.strip()}"
                )

            merge_result = subprocess.run(
                ["gh", "pr", "merge", pr_number, "--auto", "--squash", "--delete-branch"],
                capture_output=True,
                text=True,
                check=False,
            )
            if merge_result.returncode != 0:
                msg = merge_result.stderr.strip()
                console.print(f"  [yellow]⚠[/yellow] Failed to enable auto-merge: {msg}")
    else:
        if not updates:
            return

        if dry_run:
            return

        for u in updates:
            metadata[u["package"]]["version"] = u["to_version"]

        sha_map = _update_sha256_for_updates(metadata, updates)

        for u in updates:
            pkg = u["package"]
            sha = sha_map.get(pkg)
            sha_str = (
                f"  [dim]sha256: {sha[:16]}...[/dim]"
                if sha
                else "  [yellow]sha256: not found[/yellow]"
            )
            console.print(
                f"  [green]✓[/green] {pkg}: {u['from_version']} → {u['to_version']}{sha_str}"
            )
            if "checked_versions" in u:
                chain = _format_checked_versions(u["checked_versions"])
                console.print(f"    walked: {chain}")

        write_metadata(metadata)
        metadata_cache.clear()
