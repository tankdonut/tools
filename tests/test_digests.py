from unittest.mock import Mock, patch

from tasks.lib import (
    _extract_hex_from_digest,
    _parse_checksum_line,
    fetch_asset_digest,
    render_download_url_for_linux_amd64,
)


class TestExtractHexFromDigest:
    def test_sha256_prefix(self):
        assert _extract_hex_from_digest("sha256:" + "ab" * 32) == "ab" * 32

    def test_bare_hex(self):
        hex_val = "a1b2c3d4" * 8
        assert _extract_hex_from_digest(hex_val) == hex_val.lower()

    def test_empty_string(self):
        assert _extract_hex_from_digest("") is None

    def test_none_like(self):
        assert _extract_hex_from_digest("  ") is None

    def test_non_sha256_prefix(self):
        assert _extract_hex_from_digest("md5:abc123") is None


class TestParseChecksumLine:
    def test_standard_format(self):
        content = "abc123  myfile.tar.gz\ndef456  other.tar.gz"
        result = _parse_checksum_line(content, "myfile.tar.gz", "standard")
        assert result == "abc123"

    def test_standard_format_just_filename(self):
        content = "abc123  myfile.tar.gz"
        result = _parse_checksum_line(content, "myfile.tar.gz", "standard")
        assert result == "abc123"

    def test_standard_no_match(self):
        content = "abc123  other.tar.gz"
        result = _parse_checksum_line(content, "myfile.tar.gz", "standard")
        assert result is None

    def test_dist_prefix_format(self):
        content = "abc123  _dist/myfile.tar.gz"
        result = _parse_checksum_line(content, "myfile.tar.gz", "dist_prefix")
        assert result == "abc123"

    def test_bare_format(self):
        hex_val = "a1b2c3d4" * 8
        content = hex_val
        result = _parse_checksum_line(content, "anything", "bare")
        assert result == hex_val

    def test_empty_content(self):
        assert _parse_checksum_line("", "file.tar.gz", "standard") is None


class TestRenderDownloadUrlForLinuxAmd64:
    def test_simple_template(self):
        meta = {
            "download_url": "https://example.com/{{version}}/{{name}}-{{os}}-{{arch}}.tar.gz",
            "version": "1.2.3",
        }
        result = render_download_url_for_linux_amd64("mytool", meta)
        assert result == "https://example.com/1.2.3/mytool-linux-amd64.tar.gz"

    def test_rust_arch_template(self):
        meta = {
            "download_url": "https://example.com/{{name}}-{{rust_arch}}.tar.gz",
            "version": "1.0.0",
        }
        result = render_download_url_for_linux_amd64("mytool", meta)
        assert result == "https://example.com/mytool-x86_64.tar.gz"

    def test_k3d_conditional_template(self):
        meta = {
            "download_url": (
                "{{repo_url}}/releases/download/v{{version}}/"
                "{{name}}-{{os}}-{{arch}}{{ '.exe' if os == 'windows' else ''}}"
            ),
            "version": "5.8.3",
            "repo_url": "https://github.com/k3d-io/k3d",
        }
        result = render_download_url_for_linux_amd64("k3d", meta)
        assert result == "https://github.com/k3d-io/k3d/releases/download/v5.8.3/k3d-linux-amd64"


class TestFetchAssetDigest:
    @patch("tasks.lib.digests._resolve_release_tag")
    @patch("tasks.lib.digests.subprocess.run")
    def test_api_returns_digest(self, mock_run, mock_tag):
        mock_tag.return_value = "v1.2.3"
        hex_val = "ab" * 32
        mock_run.return_value = Mock(returncode=0, stdout=f"sha256:{hex_val}\n")

        result = fetch_asset_digest("owner", "repo", "1.2.3", "tool-linux-amd64.tar.gz", "tool", {})
        assert result == hex_val

    @patch("tasks.lib.digests._resolve_release_tag")
    @patch("tasks.lib.digests.subprocess.run")
    def test_api_returns_null_digest_tries_fallback(self, mock_run, mock_tag):
        mock_tag.return_value = "v1.2.3"
        # First call (API digest) returns empty
        mock_run.return_value = Mock(returncode=0, stdout="")

        with patch("tasks.lib.digests._fetch_digest_fallback", return_value="fallback_hash"):
            result = fetch_asset_digest(
                "owner", "repo", "1.2.3", "tool-linux-amd64.tar.gz", "tool", {}
            )
            assert result == "fallback_hash"

    @patch("tasks.lib.digests._fetch_hashicorp_sha256")
    def test_hashicorp_tool(self, mock_hc):
        mock_hc.return_value = "hashicorp_hash_abc123"
        result = fetch_asset_digest(
            "hashicorp", "terraform", "1.5.0", "terraform.zip", "terraform", {}
        )
        assert result == "hashicorp_hash_abc123"
        mock_hc.assert_called_once_with("terraform", "1.5.0")

    @patch("tasks.lib.digests._fetch_hashicorp_sha256")
    def test_packer_tool(self, mock_hc):
        mock_hc.return_value = "packer_hash"
        result = fetch_asset_digest("hashicorp", "packer", "1.10.0", "packer.zip", "packer", {})
        assert result == "packer_hash"

    def test_asdf_skipped(self):
        result = fetch_asset_digest("asdf-vm", "asdf", "0.18.1", "asdf.tar.gz", "asdf", {})
        assert result is None


class TestResolveReleaseTag:
    @patch("tasks.lib.digests.subprocess.run")
    def test_v_prefix_found(self, mock_run):
        from tasks.lib import _resolve_release_tag

        mock_run.return_value = Mock(returncode=0, stdout="v1.2.3\n")
        result = _resolve_release_tag("owner", "repo", "1.2.3")
        assert result == "v1.2.3"

    @patch("tasks.lib.digests.subprocess.run")
    def test_kustomize_tag_fallback(self, mock_run):
        from tasks.lib import _resolve_release_tag

        # First call (v prefix) fails, second (kustomize/) succeeds
        mock_run.side_effect = [
            Mock(returncode=1, stdout=""),
            Mock(returncode=0, stdout="kustomize/v5.8.1\n"),
        ]
        result = _resolve_release_tag("kubernetes-sigs", "kustomize", "5.8.1")
        assert result == "kustomize/v5.8.1"

    @patch("tasks.lib.digests.subprocess.run")
    def test_no_tag_found(self, mock_run):
        from tasks.lib import _resolve_release_tag

        mock_run.return_value = Mock(returncode=1, stdout="")
        result = _resolve_release_tag("owner", "repo", "9.9.9")
        assert result is None


class TestFetchHashiCorpSha256:
    @patch("tasks.lib.digests._fetch_url_content")
    def test_found(self, mock_fetch):
        from tasks.lib import _fetch_hashicorp_sha256

        mock_fetch.return_value = (
            "abc123  terraform_1.5.0_linux_amd64.zip\ndef456  terraform_1.5.0_linux_arm64.zip\n"
        )
        result = _fetch_hashicorp_sha256("terraform", "1.5.0")
        assert result == "abc123"

    @patch("tasks.lib.digests._fetch_url_content")
    def test_not_found(self, mock_fetch):
        from tasks.lib import _fetch_hashicorp_sha256

        mock_fetch.return_value = None
        result = _fetch_hashicorp_sha256("terraform", "1.5.0")
        assert result is None


class TestDigestsTask:
    @patch("tasks.tools.metadata_cache")
    @patch("tasks.tools.write_metadata")
    @patch("tasks.tools.fetch_asset_digest")
    @patch("tasks.tools.render_download_url_for_linux_amd64")
    @patch("tasks.tools.Console")
    def test_digests_task_updates_metadata(
        self, mock_console_cls, mock_render, mock_fetch, mock_write, mock_cache
    ):
        from invoke.context import Context
        from tasks.tools import digests

        mock_cache.get.return_value = {
            "mytool": {
                "version": "1.0.0",
                "repo_url": "https://github.com/owner/repo",
                "download_url": "https://example.com/{{name}}-{{os}}-{{arch}}",
                "license": "MIT",
                "description": "A tool",
            }
        }
        mock_cache.clear = Mock()
        mock_render.return_value = "https://example.com/mytool-linux-amd64"
        mock_fetch.return_value = "abc123def456" * 4

        ctx = Context()
        digests(ctx)

        mock_write.assert_called_once()
        mock_cache.clear.assert_called_once()

        written_meta = mock_write.call_args[0][0]
        assert written_meta["mytool"]["sha256"] == "abc123def456" * 4

    @patch("tasks.tools.metadata_cache")
    @patch("tasks.tools.write_metadata")
    @patch("tasks.tools.fetch_asset_digest")
    @patch("tasks.tools.render_download_url_for_linux_amd64")
    @patch("tasks.tools.Console")
    def test_digests_task_single_tool(
        self, mock_console_cls, mock_render, mock_fetch, mock_write, mock_cache
    ):
        from invoke.context import Context
        from tasks.tools import digests

        mock_cache.get.return_value = {
            "tool-a": {
                "version": "1.0.0",
                "repo_url": "https://github.com/owner/a",
                "download_url": "https://example.com/a",
                "license": "MIT",
                "description": "Tool A",
            },
            "tool-b": {
                "version": "2.0.0",
                "repo_url": "https://github.com/owner/b",
                "download_url": "https://example.com/b",
                "license": "MIT",
                "description": "Tool B",
            },
        }
        mock_cache.clear = Mock()
        mock_render.return_value = "https://example.com/tool-a-linux-amd64"
        mock_fetch.return_value = "abc123"

        ctx = Context()
        digests(ctx, name="tool-a")

        # Only tool-a should be processed
        mock_fetch.assert_called_once()

    @patch("tasks.tools.metadata_cache")
    @patch("tasks.tools.write_metadata")
    @patch("tasks.tools.Console")
    def test_digests_skips_asdf(self, mock_console_cls, mock_write, mock_cache):
        from invoke.context import Context
        from tasks.tools import digests

        mock_cache.get.return_value = {
            "asdf": {
                "version": "0.18.1",
                "repo_url": "https://github.com/asdf-vm/asdf",
                "download_url": "https://example.com/asdf.tar.gz",
                "license": "MIT",
                "description": "asdf",
            }
        }
        mock_cache.clear = Mock()

        ctx = Context()
        digests(ctx)

        mock_write.assert_not_called()

    @patch("tasks.tools.metadata_cache")
    @patch("tasks.tools.write_metadata")
    @patch("tasks.tools.Console")
    def test_digests_unknown_tool(self, mock_console_cls, mock_write, mock_cache):
        from invoke.context import Context
        from tasks.tools import digests

        mock_cache.get.return_value = {}

        ctx = Context()
        digests(ctx, name="nonexistent")

        mock_write.assert_not_called()
