from tasks.lib import load_metadata
from tasks.tools import render_metadata, validate_metadata

SHA256_HEX = "a" * 64


class TestSchemaSHA256:
    def test_schema_validates_metadata_with_sha256(self) -> None:
        """Schema accepts metadata that includes sha256 field."""
        metadata = {
            "test-tool": {
                "description": "A test tool",
                "download_url": "https://example.com/{{version}}/tool.tar.gz",
                "repo_url": "https://github.com/test/tool",
                "license": "MIT",
                "version": "1.0.0",
                "sha256": SHA256_HEX,
            },
        }
        validate_metadata(metadata)

    def test_schema_validates_metadata_without_sha256(self) -> None:
        """Schema accepts metadata without sha256 (backward compat)."""
        metadata = {
            "test-tool": {
                "description": "A test tool",
                "download_url": "https://example.com/{{version}}/tool.tar.gz",
                "repo_url": "https://github.com/test/tool",
                "license": "MIT",
                "version": "1.0.0",
            },
        }
        validate_metadata(metadata)

    def test_existing_metadata_validates_against_updated_schema(self) -> None:
        """Current metadata.yaml still validates with new schema."""
        metadata = load_metadata()
        validate_metadata(metadata)


class TestTemplateSHA256:
    def test_template_renders_with_sha256(self) -> None:
        """Template outputs sha256 field when present in metadata."""
        metadata = {
            "test-tool": {
                "description": "A test tool",
                "download_url": "https://example.com/{{version}}/tool.tar.gz",
                "repo_url": "https://github.com/test/tool",
                "license": "MIT",
                "version": "1.0.0",
                "sha256": SHA256_HEX,
            },
        }
        output = render_metadata(metadata)
        assert f"sha256: {SHA256_HEX}" in output

    def test_template_renders_without_sha256(self) -> None:
        """Template does not output sha256 when absent."""
        metadata = {
            "test-tool": {
                "description": "A test tool",
                "download_url": "https://example.com/{{version}}/tool.tar.gz",
                "repo_url": "https://github.com/test/tool",
                "license": "MIT",
                "version": "1.0.0",
            },
        }
        output = render_metadata(metadata)
        assert "sha256" not in output
