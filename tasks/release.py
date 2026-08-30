from dataclasses import dataclass
import datetime
from pathlib import Path
import re

from invoke import Context, task


@dataclass(frozen=True)
class VersionChange:
    name: str
    old_version: str | None
    new_version: str | None
    change_type: str


def calculate_calver_tag(today: datetime.date, existing_tags: list[str]) -> str:
    """Generate a CalVer tag in YYYY.MM.N format."""
    prefix = f"{today.year}.{today.month:02d}"
    max_n = -1
    for tag in existing_tags:
        if tag.startswith(prefix + "."):
            suffix = tag[len(prefix) + 1 :]
            try:
                n = int(suffix)
                if n > max_n:
                    max_n = n
            except ValueError:
                continue
    if max_n >= 0:
        return f"{prefix}.{max_n + 1}"
    return f"{prefix}.0"


def parse_metadata_diff(diff_text: str) -> list[VersionChange]:
    """Parse unified git diff of metadata.yaml to detect version changes."""
    if not diff_text.strip():
        return []

    old_versions: dict[str, str] = {}
    new_versions: dict[str, str] = {}
    current_package = ""

    for line in diff_text.splitlines():
        if not line or line.startswith(("---", "+++", "@@", "\\")):
            continue

        if line[0] == "+":
            prefix = "+"
            content = line[1:]
        elif line[0] == "-":
            prefix = "-"
            content = line[1:]
        elif line[0] == " ":
            prefix = " "
            content = line[1:]
        else:
            continue

        key_match = re.match(r"^(\S+):$", content)
        if key_match:
            current_package = key_match.group(1)
            continue

        version_match = re.match(r"^\s+version:\s*['\"]?([^'\"]+)['\"]?\s*$", content)
        if version_match and current_package:
            version_value = version_match.group(1).strip()
            if prefix == "-":
                old_versions[current_package] = version_value
            elif prefix == "+":
                new_versions[current_package] = version_value

    changes: list[VersionChange] = []
    all_packages = sorted(set(old_versions.keys()) | set(new_versions.keys()))

    for pkg in all_packages:
        old = old_versions.get(pkg)
        new = new_versions.get(pkg)
        if old and new:
            changes.append(
                VersionChange(name=pkg, old_version=old, new_version=new, change_type="upgrade")
            )
        elif new:
            changes.append(
                VersionChange(name=pkg, old_version=None, new_version=new, change_type="addition")
            )
        elif old:
            changes.append(
                VersionChange(name=pkg, old_version=old, new_version=None, change_type="removal")
            )

    return changes


def generate_changelog(changes: list[VersionChange]) -> str:
    """Generate a changelog string from version changes, grouped by type."""
    if not changes:
        return ""

    sections: list[str] = []

    upgrades = [c for c in changes if c.change_type == "upgrade"]
    if upgrades:
        lines = ["### Upgrades"]
        for c in upgrades:
            lines.append(f"- {c.name}: {c.old_version} \u2192 {c.new_version}")
        sections.append("\n".join(lines))

    additions = [c for c in changes if c.change_type == "addition"]
    if additions:
        lines = ["### Additions"]
        for c in additions:
            lines.append(f"- {c.name}: {c.new_version}")
        sections.append("\n".join(lines))

    removals = [c for c in changes if c.change_type == "removal"]
    if removals:
        lines = ["### Removals"]
        for c in removals:
            lines.append(f"- {c.name}")
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def has_version_changes(diff_text: str) -> bool:
    """Return True if the diff contains any version field changes."""
    for line in diff_text.splitlines():
        if not line or line.startswith(("---", "+++", "@@", "\\")):
            continue
        if line[0] in ("+", "-"):
            content = line[1:]
            if re.match(r"^\s*version:\s*", content):
                return True
    return False


def update_changelog_file(
    path: Path, tag: str, date_str: str, changes: list[VersionChange]
) -> None:
    """Prepend a new changelog entry to the file at the given path."""
    if not changes:
        return

    entry = f"## {tag} ({date_str})\n{generate_changelog(changes)}"

    if path.exists():
        existing = path.read_text()
        path.write_text(f"{entry}\n\n{existing}")
    else:
        path.write_text(entry)


def build_release_notes(
    tag: str, image: str, digest: str | None, changes: list[VersionChange]
) -> str:
    """Compose GitHub release notes: image pin plus grouped tool changes."""
    lines = [f"Image: `{image}:{tag}`"]
    if digest:
        lines.append("")
        lines.append(f"Digest `{digest}` — pin: `{image}:{tag}@{digest}`")
    changelog = generate_changelog(changes)
    if changelog:
        lines.append("")
        lines.append(changelog)
    return "\n".join(lines)


def bump_pyproject_version(path: Path, version: str) -> bool:
    """Set the first `version = "..."` assignment in pyproject.toml.

    Returns True if the file content changed, False if it already held the
    given version.
    """
    content = path.read_text()
    updated = re.sub(r'version = ".*"', f'version = "{version}"', content, count=1)
    if updated == content:
        return False
    path.write_text(updated)
    return True


@task
def release(ctx: Context) -> None:
    """Run the release automation process."""
