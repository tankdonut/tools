from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SAMPLE_METADATA = {
    "test-pkg1": {
        "description": "Test package 1",
        "download_url": "https://example.com/{{version}}/{{name}}.tar.gz",
        "repo_url": "https://github.com/test/repo1",
        "license": "MIT",
        "version": "1.0.0",
    },
    "test-pkg2": {
        "description": "Test package 2",
        "download_url": "https://example.com/{{version}}/{{name}}.tar.gz",
        "repo_url": "git@github.com:test/repo2.git",
        "license": "APACHE-2.0",
        "version": "2.0.0",
    },
}


@pytest.fixture
def sample_metadata():
    """Return sample metadata dict."""
    return SAMPLE_METADATA.copy()


@pytest.fixture
def temp_metadata_file(sample_metadata):
    """Create a temporary metadata file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(sample_metadata, f)
        temp_path = Path(f.name)
    yield temp_path
    temp_path.unlink()


@pytest.fixture
def mock_github_api_response():
    """Mock GitHub API response."""
    return {
        "tag_name": "v2.1.0",
        "name": "Release 2.1.0",
        "html_url": "https://github.com/test/repo1/releases/tag/v2.1.0",
    }


@pytest.fixture
def mock_subprocess_run():
    """Mock subprocess.run for git commands."""
    with patch("subprocess.run") as mock:
        mock.return_value = Mock(stdout="", stderr="", returncode=0)
        yield mock
