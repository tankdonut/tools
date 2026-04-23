import datetime

from tasks.release import (
    VersionChange,
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
