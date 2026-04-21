import json
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from jsonschema import validate

from tasks.lib import METADATA_FILE, METADATA_SCHEMA_FILE, MetadataCache

logger = logging.getLogger(__name__)

metadata_cache = MetadataCache()

TEMPLATE_DIR = Path(METADATA_FILE).parent
TEMPLATE_NAME = "metadata.yaml.j2"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(disabled_extensions=("yml", "yaml", "jinja2", "j2")),
    trim_blocks=True,
    lstrip_blocks=True,
)

template = env.get_template(TEMPLATE_NAME)


def load_metadata_schema() -> dict:
    if not METADATA_SCHEMA_FILE.exists():
        raise FileNotFoundError(f"Metadata schema file not found: {METADATA_SCHEMA_FILE}")
    with METADATA_SCHEMA_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_metadata(metadata: dict) -> None:
    schema = load_metadata_schema()
    validate(instance=metadata, schema=schema)


def render_metadata(metadata: dict) -> str:
    return template.render(metadata=metadata)


def write_metadata(metadata: dict) -> None:
    rendered = render_metadata(metadata)
    validate_metadata(metadata)
    METADATA_FILE.write_text(rendered, encoding="utf-8")
