from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).parent.parent.parent.resolve()

METADATA_FILE = Path(__file__).parent.parent / "metadata.yaml"
METADATA_SCHEMA_FILE = Path(METADATA_FILE).with_suffix(".schema.json")


def load_metadata() -> Any:
    with METADATA_FILE.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class MetadataCache:
    """Simple in-memory cache for metadata."""

    _instance = None
    _metadata: dict | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get(self) -> Any:
        """Get cached metadata or load it."""
        if self._metadata is None:
            self._metadata = load_metadata()
        return self._metadata

    def clear(self) -> None:
        """Clear cache."""
        self._metadata = None
