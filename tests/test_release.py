import datetime

from invoke import Context
import pytest
from tasks import release as release_mod
from tasks.release import (
    VersionChange,
    build_release_notes,
    bump_pyproject_version,
    calculate_calver_tag,
    generate_changelog,
    has_version_changes,
    parse_metadata_diff,
    update_changelog_file,
)


class TestCalculateCalverTag:
    """Test calculate_calver_tag function."""

    def test_no_existing_tags(self):
        """Standard CalVer generation with no existing tags returns YYYY.MM.0."""
        today = datetime.date(2024, 1, 15)
        result = calculate_calver_tag(today, [])
        assert result == "2024.01.0"

    def test_increment_same_month(self):
        """Same-month tags increment the counter."""
        today = datetime.date(2024, 1, 15)
        result = calculate_calver_tag(today, ["2024.01.0"])
        assert result == "2024.01.1"

    def test_different_month_resets(self):
        """Different month resets counter to 0."""
        today = datetime.date(2024, 2, 10)
        result = calculate_calver_tag(today, ["2024.01.0", "2024.01.1"])
        assert result == "2024.02.0"

    def test_different_year_resets(self):
        """Different year resets counter to 0."""
        today = datetime.date(2025, 3, 1)
        result = calculate_calver_tag(today, ["2024.12.0", "2024.12.1"])
        assert result == "2025.03.0"

    def test_multiple_same_month_finds_highest(self):
        """Multiple same-month tags finds highest N and increments."""
        today = datetime.date(2024, 6, 15)
        result = calculate_calver_tag(today, ["2024.06.0", "2024.06.1", "2024.06.3"])
        assert result == "2024.06.4"

    def test_non_calver_tags_ignored(self):
        """Non-CalVer tags are ignored and do not affect the result."""
        today = datetime.date(2024, 1, 15)
        result = calculate_calver_tag(today, ["v1.0.0", "release-2024", "not-a-tag"])
        assert result == "2024.01.0"


class TestParseMetadataDiff:
    """Test parse_metadata_diff function."""

    def test_hunk_header_attribution(self):
        """Version-only hunks attribute via the @@ section key, and a
        later key line in one hunk does not leak into the next hunk."""
        diff = (
            "--- a/tasks/metadata.yaml\n"
            "+++ b/tasks/metadata.yaml\n"
            "@@ -63,8 +63,8 @@ crush:\n"
            "   repo_url: https://example.com/crush\n"
            "-  version: 0.90.0\n"
            "+  version: 0.91.0\n"
            " ct:\n"
            "   description: >\n"
            "@@ -228,8 +228,8 @@ opencode:\n"
            "   repo_url: https://example.com/opencode\n"
            "-  version: 1.18.19\n"
            "+  version: 1.18.21\n"
        )
        changes = parse_metadata_diff(diff)
        assert [(c.name, c.old_version, c.new_version) for c in changes] == [
            ("crush", "0.90.0", "0.91.0"),
            ("opencode", "1.18.19", "1.18.21"),
        ]

    def test_single_version_upgrade(self):
        """Single version upgrade detects old and new version."""
        diff = (
            "--- a/metadata.yaml\n"
            "+++ b/metadata.yaml\n"
            "@@ -1,4 +1,4 @@\n"
            " tool-a:\n"
            '   description: "Tool A"\n'
            '-  version: "1.0.0"\n'
            '+  version: "2.0.0"\n'
        )
        changes = parse_metadata_diff(diff)
        assert len(changes) == 1
        assert changes[0].name == "tool-a"
        assert changes[0].old_version == "1.0.0"
        assert changes[0].new_version == "2.0.0"
        assert changes[0].change_type == "upgrade"

    def test_multiple_upgrades(self):
        """Multiple upgrades detected in a single diff."""
        diff = (
            "--- a/metadata.yaml\n"
            "+++ b/metadata.yaml\n"
            "@@ -1,8 +1,8 @@\n"
            " tool-a:\n"
            '   description: "Tool A"\n'
            '-  version: "1.0.0"\n'
            '+  version: "2.0.0"\n'
            " tool-b:\n"
            '   description: "Tool B"\n'
            '-  version: "3.0.0"\n'
            '+  version: "4.0.0"\n'
        )
        changes = parse_metadata_diff(diff)
        assert len(changes) == 2
        assert changes[0].name == "tool-a"
        assert changes[0].change_type == "upgrade"
        assert changes[1].name == "tool-b"
        assert changes[1].change_type == "upgrade"

    def test_package_addition(self):
        """Package addition detected from new +version line without old version."""
        diff = (
            "--- a/metadata.yaml\n"
            "+++ b/metadata.yaml\n"
            "@@ -1,2 +1,5 @@\n"
            " existing-tool:\n"
            '   description: "Existing"\n'
            "+new-tool:\n"
            '+  description: "New tool"\n'
            '+  version: "1.0.0"\n'
        )
        changes = parse_metadata_diff(diff)
        assert len(changes) == 1
        assert changes[0].name == "new-tool"
        assert changes[0].old_version is None
        assert changes[0].new_version == "1.0.0"
        assert changes[0].change_type == "addition"

    def test_package_removal(self):
        """Package removal detected from deleted -version line without new version."""
        diff = (
            "--- a/metadata.yaml\n"
            "+++ b/metadata.yaml\n"
            "@@ -1,5 +1,2 @@\n"
            "-old-tool:\n"
            '-  description: "Old tool"\n'
            '-  version: "0.5.0"\n'
            " remaining-tool:\n"
            '   description: "Remaining"\n'
        )
        changes = parse_metadata_diff(diff)
        assert len(changes) == 1
        assert changes[0].name == "old-tool"
        assert changes[0].old_version == "0.5.0"
        assert changes[0].new_version is None
        assert changes[0].change_type == "removal"

    def test_description_change_ignored(self):
        """Description changes produce no version changes."""
        diff = (
            "--- a/metadata.yaml\n"
            "+++ b/metadata.yaml\n"
            "@@ -1,4 +1,4 @@\n"
            " tool-a:\n"
            '-  description: "Old description"\n'
            '+  description: "New description"\n'
            '   version: "1.0.0"\n'
        )
        changes = parse_metadata_diff(diff)
        assert changes == []

    def test_url_change_ignored(self):
        """URL changes produce no version changes."""
        diff = (
            "--- a/metadata.yaml\n"
            "+++ b/metadata.yaml\n"
            "@@ -1,4 +1,4 @@\n"
            " tool-a:\n"
            '   description: "Tool A"\n'
            '-  download_url: "https://old.example.com"\n'
            '+  download_url: "https://new.example.com"\n'
        )
        changes = parse_metadata_diff(diff)
        assert changes == []

    def test_empty_diff(self):
        """Empty diff returns empty list."""
        changes = parse_metadata_diff("")
        assert changes == []

    def test_mixed_changes(self):
        """Mixed upgrade, addition, and removal in one diff."""
        diff = (
            "--- a/metadata.yaml\n"
            "+++ b/metadata.yaml\n"
            "@@ -1,9 +1,9 @@\n"
            " upgraded-pkg:\n"
            '   description: "Up"\n'
            '-  version: "1.0.0"\n'
            '+  version: "2.0.0"\n'
            "-removed-pkg:\n"
            '-  description: "Gone"\n'
            '-  version: "0.5.0"\n'
            "+added-pkg:\n"
            '+  description: "New"\n'
            '+  version: "3.0.0"\n'
        )
        changes = parse_metadata_diff(diff)
        assert len(changes) == 3
        by_name = {c.name: c for c in changes}
        assert by_name["upgraded-pkg"].change_type == "upgrade"
        assert by_name["removed-pkg"].change_type == "removal"
        assert by_name["added-pkg"].change_type == "addition"


class TestGenerateChangelog:
    """Test generate_changelog function."""

    def test_upgrade_formatting(self):
        """Upgrade entries format as name: old_version → new_version."""
        changes = [
            VersionChange(name="pkg", old_version="1.0", new_version="2.0", change_type="upgrade"),
        ]
        result = generate_changelog(changes)
        assert result == "### Upgrades\n- pkg: 1.0 \u2192 2.0"

    def test_addition_formatting(self):
        """Addition entries format as name: new_version."""
        changes = [
            VersionChange(name="pkg", old_version=None, new_version="1.0", change_type="addition"),
        ]
        result = generate_changelog(changes)
        assert result == "### Additions\n- pkg: 1.0"

    def test_removal_formatting(self):
        """Removal entries format as just name without version."""
        changes = [
            VersionChange(name="pkg", old_version="0.5", new_version=None, change_type="removal"),
        ]
        result = generate_changelog(changes)
        assert result == "### Removals\n- pkg"

    def test_mixed_changes_grouped(self):
        """Mixed changes are grouped in order: upgrades, additions, removals."""
        changes = [
            VersionChange(name="pkg1", old_version="1.0", new_version="2.0", change_type="upgrade"),
            VersionChange(name="pkg2", old_version=None, new_version="1.0", change_type="addition"),
            VersionChange(name="pkg3", old_version="0.5", new_version=None, change_type="removal"),
        ]
        result = generate_changelog(changes)
        assert "### Upgrades" in result
        assert "### Additions" in result
        assert "### Removals" in result
        assert result.index("### Upgrades") < result.index("### Additions")
        assert result.index("### Additions") < result.index("### Removals")

    def test_empty_changes_returns_empty_string(self):
        """Empty changes list returns empty string."""
        result = generate_changelog([])
        assert result == ""


class TestHasVersionChanges:
    """Test has_version_changes function."""

    def test_returns_true_for_version_change(self):
        """Returns True when diff contains a version change."""
        diff = (
            "--- a/metadata.yaml\n"
            "+++ b/metadata.yaml\n"
            "@@ -1,3 +1,3 @@\n"
            " tool-a:\n"
            '-  version: "1.0.0"\n'
            '+  version: "2.0.0"\n'
        )
        assert has_version_changes(diff) is True

    def test_returns_false_for_description_only(self):
        """Returns False for description-only changes."""
        diff = (
            "--- a/metadata.yaml\n"
            "+++ b/metadata.yaml\n"
            "@@ -1,3 +1,3 @@\n"
            " tool-a:\n"
            '-  description: "Old"\n'
            '+  description: "New"\n'
        )
        assert has_version_changes(diff) is False

    def test_returns_false_for_empty_diff(self):
        """Returns False for empty diff."""
        assert has_version_changes("") is False

    def test_returns_false_for_url_only(self):
        """Returns False for URL-only changes."""
        diff = (
            "--- a/metadata.yaml\n"
            "+++ b/metadata.yaml\n"
            "@@ -1,3 +1,3 @@\n"
            " tool-a:\n"
            '-  download_url: "https://old.example.com"\n'
            '+  download_url: "https://new.example.com"\n'
        )
        assert has_version_changes(diff) is False

    def test_returns_true_for_mixed_version_and_description(self):
        """Returns True when diff has both version and description changes."""
        diff = (
            "--- a/metadata.yaml\n"
            "+++ b/metadata.yaml\n"
            "@@ -1,4 +1,4 @@\n"
            " tool-a:\n"
            '-  description: "Old"\n'
            '+  description: "New"\n'
            '-  version: "1.0.0"\n'
            '+  version: "2.0.0"\n'
        )
        assert has_version_changes(diff) is True


class TestUpdateChangelogFile:
    """Test update_changelog_file function."""

    def test_creates_new_file_when_not_exists(self, tmp_path):
        """Creates a new changelog file when it does not exist."""
        changelog = tmp_path / "CHANGELOG.md"
        changes = [
            VersionChange(name="pkg", old_version="1.0", new_version="2.0", change_type="upgrade"),
        ]
        update_changelog_file(changelog, "2024.01.0", "2024-01-15", changes)
        assert changelog.exists()
        content = changelog.read_text()
        assert "## 2024.01.0 (2024-01-15)" in content
        assert "### Upgrades" in content

    def test_prepends_to_existing_file(self, tmp_path):
        """Prepends new entry before existing content."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("## 2023.12.0 (2023-12-01)\n### Upgrades\n- old: 0.5 \u2192 1.0")
        changes = [
            VersionChange(name="pkg", old_version="1.0", new_version="2.0", change_type="upgrade"),
        ]
        update_changelog_file(changelog, "2024.01.0", "2024-01-15", changes)
        content = changelog.read_text()
        assert content.startswith("## 2024.01.0 (2024-01-15)")
        assert "## 2023.12.0 (2023-12-01)" in content

    def test_entry_format_starts_with_header(self, tmp_path):
        """Generated entry starts with the expected header format."""
        changelog = tmp_path / "CHANGELOG.md"
        changes = [
            VersionChange(name="pkg", old_version="1.0", new_version="2.0", change_type="upgrade"),
        ]
        update_changelog_file(changelog, "2024.01.0", "2024-01-15", changes)
        content = changelog.read_text()
        assert content.startswith("## 2024.01.0 (2024-01-15)\n### Upgrades")

    def test_empty_changes_is_noop_for_missing_file(self, tmp_path):
        """Empty changes list does not create a file when it does not exist."""
        changelog = tmp_path / "CHANGELOG.md"
        update_changelog_file(changelog, "2024.01.0", "2024-01-15", [])
        assert not changelog.exists()

    def test_empty_changes_is_noop_for_existing_file(self, tmp_path):
        """Empty changes list does not modify an existing file."""
        changelog = tmp_path / "CHANGELOG.md"
        original = "## 2023.12.0 (2023-12-01)\n### Upgrades\n- pkg: 0.5 \u2192 1.0\n"
        changelog.write_text(original)
        update_changelog_file(changelog, "2024.01.0", "2024-01-15", [])
        assert changelog.read_text() == original

    def test_existing_content_preserved_after_prepend(self, tmp_path):
        """Existing content is fully preserved after prepending a new entry."""
        changelog = tmp_path / "CHANGELOG.md"
        existing_body = "## 2023.12.0 (2023-12-01)\n### Upgrades\n- old-pkg: 0.5 \u2192 1.0\n"
        changelog.write_text(existing_body)
        changes = [
            VersionChange(
                name="new-pkg", old_version=None, new_version="3.0", change_type="addition"
            ),
        ]
        update_changelog_file(changelog, "2024.01.0", "2024-01-15", changes)
        content = changelog.read_text()
        assert "## 2023.12.0 (2023-12-01)" in content
        assert "### Upgrades\n- old-pkg: 0.5 \u2192 1.0" in content
        assert "### Additions\n- new-pkg: 3.0" in content


class TestBuildReleaseNotes:
    """Test build_release_notes function."""

    def test_full_format_with_digest_and_changes(self):
        """Notes contain image ref, digest pin, and changelog sections."""
        changes = [
            VersionChange(name="pkg", old_version="1.0", new_version="2.0", change_type="upgrade"),
        ]
        result = build_release_notes(
            "2024.01.0", "ghcr.io/tankdonut/tools", "sha256:abc123", changes
        )
        assert result == (
            "Image: `ghcr.io/tankdonut/tools:2024.01.0`\n"
            "\n"
            "Digest `sha256:abc123` — pin: `ghcr.io/tankdonut/tools:2024.01.0@sha256:abc123`\n"
            "\n"
            "### Upgrades\n"
            "- pkg: 1.0 \u2192 2.0"
        )

    def test_without_digest_omits_pin_line(self):
        """A None digest omits the digest pin entirely."""
        changes = [
            VersionChange(name="pkg", old_version="1.0", new_version="2.0", change_type="upgrade"),
        ]
        result = build_release_notes("2024.01.0", "ghcr.io/tankdonut/tools", None, changes)
        assert result == (
            "Image: `ghcr.io/tankdonut/tools:2024.01.0`\n\n### Upgrades\n- pkg: 1.0 \u2192 2.0"
        )

    def test_without_changes_is_image_only(self):
        """Empty changes list yields notes with only the image line."""
        result = build_release_notes("2024.01.0", "ghcr.io/tankdonut/tools", "sha256:abc123", [])
        assert result == (
            "Image: `ghcr.io/tankdonut/tools:2024.01.0`\n"
            "\n"
            "Digest `sha256:abc123` — pin: `ghcr.io/tankdonut/tools:2024.01.0@sha256:abc123`"
        )


class TestBumpPyprojectVersion:
    """Test bump_pyproject_version function."""

    def test_replaces_version_and_returns_true(self, tmp_path):
        """The first version assignment is replaced and True is returned."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "packages"\nversion = "1.0.0"\n')
        changed = bump_pyproject_version(pyproject, "2024.01.0")
        assert changed is True
        content = pyproject.read_text()
        assert 'version = "2024.01.0"' in content
        assert 'version = "1.0.0"' not in content

    def test_only_first_assignment_replaced(self, tmp_path):
        """Only the first version assignment is rewritten."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('version = "1.0.0"\nversion = "9.9.9"\n')
        bump_pyproject_version(pyproject, "2024.01.0")
        content = pyproject.read_text()
        assert content == 'version = "2024.01.0"\nversion = "9.9.9"\n'

    def test_already_at_version_returns_false(self, tmp_path):
        """An unchanged file returns False and is left untouched."""
        pyproject = tmp_path / "pyproject.toml"
        original = '[project]\nversion = "2024.01.0"\n'
        pyproject.write_text(original)
        changed = bump_pyproject_version(pyproject, "2024.01.0")
        assert changed is False
        assert pyproject.read_text() == original

    def test_preserves_surrounding_content(self, tmp_path):
        """All other keys and sections survive the rewrite."""
        pyproject = tmp_path / "pyproject.toml"
        original = (
            "[project]\n"
            'name = "packages"\n'
            'version = "1.0.0"\n'
            'requires-python = ">=3.13,<4.0"\n'
            "\n"
            "[tool.ruff]\n"
            "line-length = 100\n"
        )
        pyproject.write_text(original)
        bump_pyproject_version(pyproject, "2026.08.0")
        content = pyproject.read_text()
        assert 'name = "packages"' in content
        assert 'requires-python = ">=3.13,<4.0"' in content
        assert "[tool.ruff]" in content
        assert "line-length = 100" in content


class TestPickLatestTag:
    """Test pick_latest_tag function."""

    def test_numeric_ordering(self):
        """Numeric component comparison, not lexicographic."""
        assert release_mod.pick_latest_tag(["2026.08.0", "2026.08.2", "2026.08.10"]) == (
            "2026.08.10"
        )

    def test_ignores_non_calver_tags(self):
        """Only YYYY.MM.N shaped tags are considered."""
        assert release_mod.pick_latest_tag(["v1.2.3", "latest", "2026.08.0"]) == "2026.08.0"

    def test_no_calver_tags_returns_none(self):
        """Returns None when no CalVer tags exist."""
        assert release_mod.pick_latest_tag(["v1.0.0", "20-dev"]) is None


class TestResolveDiffBase:
    """Test resolve_diff_base function."""

    def test_prefers_latest_release_tag(self, monkeypatch):
        """With release tags present, the highest CalVer tag is the base."""
        monkeypatch.setattr(release_mod, "_git_output", lambda *args: "2026.07.3\n2026.08.0")
        assert release_mod.resolve_diff_base() == "2026.08.0"

    def test_falls_back_to_metadata_parent(self, monkeypatch):
        """Without release tags, base is the parent of the last metadata commit."""
        responses = {
            ("tag", "-l", "20*"): "",
            ("log", "-1", "--format=%H", "--", "tasks/metadata.yaml"): "bumpsha",
            ("rev-parse", "bumpsha^"): "parentsha",
        }
        monkeypatch.setattr(release_mod, "_git_output", lambda *args: responses[args])
        assert release_mod.resolve_diff_base() == "parentsha"

    def test_raises_without_metadata_history(self, monkeypatch):
        """Fails loudly when metadata.yaml has no commit history."""
        responses = {
            ("tag", "-l", "20*"): "",
            ("log", "-1", "--format=%H", "--", "tasks/metadata.yaml"): "",
        }
        monkeypatch.setattr(release_mod, "_git_output", lambda *args: responses[args])
        with pytest.raises(RuntimeError, match="No commits found"):
            release_mod.resolve_diff_base()


class TestReleaseDiffRange:
    """Test _release_diff_range helper."""

    def test_uses_prev_tag_when_present(self, monkeypatch):
        """With PREV_TAG set, the range spans prev..tag."""
        monkeypatch.setenv("PREV_TAG", "2026.07.0")
        assert release_mod._release_diff_range("2026.08.0") == "2026.07.0..2026.08.0"

    def test_first_release_uses_pre_bump_base(self, monkeypatch):
        """Without PREV_TAG, the base is the parent of the last metadata commit."""
        monkeypatch.delenv("PREV_TAG", raising=False)
        responses = {
            ("log", "-1", "--format=%H", "--", "tasks/metadata.yaml"): "bumpsha",
            ("rev-parse", "bumpsha^"): "parentsha",
        }
        monkeypatch.setattr(release_mod, "_git_output", lambda *args: responses[args])
        assert release_mod._release_diff_range("2026.08.0") == "parentsha..2026.08.0"


class TestAppendGithubOutput:
    """Test _append_github_output helper."""

    def test_appends_pairs(self, tmp_path, monkeypatch):
        """Writes name=value lines to $GITHUB_OUTPUT."""
        out = tmp_path / "outputs.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        release_mod._append_github_output("has_changes", "true")
        release_mod._append_github_output("calver_tag", "2026.08.0")
        assert out.read_text() == "has_changes=true\ncalver_tag=2026.08.0\n"

    def test_noop_without_env(self, monkeypatch):
        """Does nothing when GITHUB_OUTPUT is unset (local runs)."""
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        release_mod._append_github_output("has_changes", "false")


class TestDetectTask:
    """Test the release.detect invoke task."""

    DIFF = "-  version: '0.90.0'\n+  version: '0.91.0'"

    def _run(self, monkeypatch, tmp_path, diff, tags):
        out = tmp_path / "outputs.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        responses = {
            ("tag", "-l", "20*"): "\n".join(tags),
            ("log", "-1", "--format=%H", "--", "tasks/metadata.yaml"): "bumpsha",
            ("rev-parse", "bumpsha^"): "parentsha",
            ("tag", "-l"): "\n".join(tags),
        }

        def fake_git(*args):
            if args[0] == "diff":
                return diff
            return responses[args]

        monkeypatch.setattr(release_mod, "_git_output", fake_git)
        monkeypatch.chdir(tmp_path)
        release_mod.detect(Context())
        return out.read_text()

    def test_no_changes_skips(self, monkeypatch, tmp_path):
        """No version changes and no recoverable tag writes has_changes=false."""
        monkeypatch.setattr(release_mod, "_release_exists", lambda tag: True)
        (tmp_path / "CHANGELOG.md").write_text("## 2026.08.0 (2026-08-30)\n")
        assert self._run(monkeypatch, tmp_path, "", ["2026.08.0"]) == "has_changes=false\n"

    def test_changes_cut_new_tag(self, monkeypatch, tmp_path):
        """Version changes produce today's CalVer tag with skip=false."""
        today = datetime.date.today()
        expected = f"{today.year}.{today.month:02d}.0"
        output = self._run(monkeypatch, tmp_path, self.DIFF, [])
        assert output == f"has_changes=true\ncalver_tag={expected}\nskip=false\n"

    def test_incomplete_release_recovers(self, monkeypatch, tmp_path):
        """Tag exists but release is missing: re-enters via skip path."""
        monkeypatch.setattr(release_mod, "_release_exists", lambda tag: False)
        output = self._run(monkeypatch, tmp_path, "", ["2026.08.0"])
        assert output == "has_changes=true\ncalver_tag=2026.08.0\nskip=true\n"

    def test_missing_changelog_recovers(self, monkeypatch, tmp_path):
        """Release exists but changelog entry missing: skip path recovery."""
        monkeypatch.setattr(release_mod, "_release_exists", lambda tag: True)
        output = self._run(monkeypatch, tmp_path, "", ["2026.08.0"])
        assert output == "has_changes=true\ncalver_tag=2026.08.0\nskip=true\n"


class TestNotesTask:
    """Test the release.notes invoke task."""

    def test_writes_notes_file(self, tmp_path, monkeypatch):
        """Composes image ref, digest pin, and changelog into release-notes.md."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RELEASE_TAG", "2026.08.0")
        monkeypatch.setenv("GITHUB_REPOSITORY", "tankdonut/tools")
        monkeypatch.setenv("IMAGE_DIGEST", "sha256:abc123")
        monkeypatch.setenv("PREV_TAG", "2026.07.0")

        captured = {}

        def fake_changes(diff_range):
            captured["range"] = diff_range
            return [
                VersionChange(
                    name="crush", old_version="0.90.0", new_version="0.91.0", change_type="upgrade"
                )
            ]

        monkeypatch.setattr(release_mod, "changes_for_range", fake_changes)
        release_mod.notes(Context())

        assert captured["range"] == "2026.07.0..2026.08.0"
        content = (tmp_path / "release-notes.md").read_text()
        assert "Image: `ghcr.io/tankdonut/tools:2026.08.0`" in content
        assert "sha256:abc123" in content
        assert "- crush: 0.90.0 → 0.91.0" in content

    def test_requires_release_tag(self, tmp_path, monkeypatch):
        """Fails loudly when RELEASE_TAG is unset."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("RELEASE_TAG", raising=False)
        with pytest.raises(RuntimeError, match="RELEASE_TAG"):
            release_mod.notes(Context())


class TestChangelogTask:
    """Test the release.changelog invoke task."""

    def test_updates_changelog_and_pyproject(self, tmp_path, monkeypatch):
        """Prepends the release entry and bumps the project version."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "tools"\nversion = "0.1.0"\n')
        monkeypatch.setenv("RELEASE_TAG", "2026.08.0")
        monkeypatch.setattr(release_mod, "_release_diff_range", lambda tag: "basesha..HEAD")
        changes = [
            VersionChange(
                name="opencode",
                old_version="1.18.19",
                new_version="1.18.21",
                change_type="upgrade",
            )
        ]
        monkeypatch.setattr(release_mod, "changes_for_range", lambda diff_range: changes)
        release_mod.changelog(Context())

        changelog_text = (tmp_path / "CHANGELOG.md").read_text()
        assert changelog_text.startswith("## 2026.08.0 (")
        assert "### Upgrades" in changelog_text
        assert "- opencode: 1.18.19 → 1.18.21" in changelog_text
        assert 'version = "2026.08.0"' in (tmp_path / "pyproject.toml").read_text()
