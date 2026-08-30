from dataclasses import dataclass
import datetime
import os
from pathlib import Path
import re
import subprocess

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


def _git_output(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable is not set: {name}")
    return value


def _append_github_output(name: str, value: str) -> None:
    output_file = os.getenv("GITHUB_OUTPUT")
    if not output_file:
        return
    with Path(output_file).open("a") as f:
        f.write(f"{name}={value}\n")


def pick_latest_tag(tags: list[str]) -> str | None:
    """Return the highest CalVer (YYYY.MM.N) tag, ignoring non-CalVer tags."""
    calver = [t for t in tags if re.fullmatch(r"\d{4}\.\d{2}\.\d+", t)]
    if not calver:
        return None
    return max(calver, key=lambda tag: [int(part) for part in tag.split(".")])


def _pre_release_base() -> str:
    """Parent of the most recent tasks/metadata.yaml commit: the state
    immediately before the current bump. Used when no earlier release
    tag exists to diff against."""
    last_meta = _git_output("log", "-1", "--format=%H", "--", "tasks/metadata.yaml")
    if not last_meta:
        raise RuntimeError("No commits found for tasks/metadata.yaml")
    return _git_output("rev-parse", f"{last_meta}^")


def resolve_diff_base() -> str:
    """Diff base for unreleased version changes: the latest release tag if
    one exists, otherwise the parent of the most recent tasks/metadata.yaml
    change. Keeps a bump detectable even when later commits only touch the
    workflow or docs, so a missed release self-heals on the next run."""
    tag = pick_latest_tag(_git_output("tag", "-l", "20*").split())
    if tag:
        return tag
    return _pre_release_base()


def changes_for_range(diff_range: str) -> list[VersionChange]:
    diff = _git_output("diff", diff_range, "--", "tasks/metadata.yaml")
    return parse_metadata_diff(diff)


def _release_exists(tag: str) -> bool:
    try:
        result = subprocess.run(["gh", "release", "view", tag], capture_output=True, text=True)
    except OSError:
        return False
    return result.returncode == 0


def _changelog_has_entry(tag: str) -> bool:
    changelog = Path("CHANGELOG.md")
    if not changelog.exists():
        return False
    return any(line.startswith(f"## {tag} ") for line in changelog.read_text().splitlines())


def _release_diff_range(tag: str) -> str:
    """Diff range covering the changes released by `tag`.

    With a previous release tag, changes are prev..tag. For the first
    release, the base is the pre-bump state — never the latest tag, which
    is this release itself and would diff to nothing.
    """
    prev = os.getenv("PREV_TAG", "")
    if prev:
        return f"{prev}..{tag}"
    return f"{_pre_release_base()}..{tag}"


@task
def detect(c: Context) -> None:
    """Report unreleased version changes and the next CalVer tag via GITHUB_OUTPUT."""
    diff = _git_output("diff", resolve_diff_base(), "HEAD", "--", "tasks/metadata.yaml")
    if not has_version_changes(diff):
        latest = pick_latest_tag(_git_output("tag", "-l", "20*").split())
        if latest and not (_release_exists(latest) and _changelog_has_entry(latest)):
            print(f"Release artifacts for {latest} incomplete; recovering.")
            _append_github_output("has_changes", "true")
            _append_github_output("calver_tag", latest)
            _append_github_output("skip", "true")
            return
        print("No tool version changes since the last release; skipping.")
        _append_github_output("has_changes", "false")
        return

    existing_tags = _git_output("tag", "-l").split()
    tag = calculate_calver_tag(datetime.date.today(), existing_tags)
    skip = "true" if tag in existing_tags else "false"
    print(f"has_changes=true calver_tag={tag} skip={skip}")
    _append_github_output("has_changes", "true")
    _append_github_output("calver_tag", tag)
    _append_github_output("skip", skip)


@task
def notes(c: Context) -> None:
    """Write release-notes.md from RELEASE_TAG, PREV_TAG, and IMAGE_DIGEST."""
    tag = _require_env("RELEASE_TAG")
    changes = changes_for_range(_release_diff_range(tag))
    image = f"ghcr.io/{_require_env('GITHUB_REPOSITORY')}"
    digest = os.getenv("IMAGE_DIGEST") or None
    content = build_release_notes(tag, image, digest, changes)
    Path("release-notes.md").write_text(content + "\n")
    print(content)


@task
def changelog(c: Context) -> None:
    """Prepend the RELEASE_TAG entry to CHANGELOG.md and bump pyproject.toml."""
    tag = _require_env("RELEASE_TAG")
    changes = changes_for_range(_release_diff_range(tag))
    update_changelog_file(Path("CHANGELOG.md"), tag, datetime.date.today().isoformat(), changes)
    bump_pyproject_version(Path("pyproject.toml"), tag)
