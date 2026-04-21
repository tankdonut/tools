from typing import Any

from jinja2 import BaseLoader, Environment

from tasks.lib.platform import get_goarch, get_os, get_rust_arch


def render_template(package_id: str, package_metadata: dict[str, Any], template_str: str) -> str:
    env = Environment(loader=BaseLoader())
    template = env.from_string(template_str)
    result = template.render(
        os=get_os(),
        arch=get_goarch(),
        rust_arch=get_rust_arch(),
        name=package_id,
        **package_metadata,
    )
    return result


def render_download_url_for_linux_amd64(package_id: str, package_metadata: dict[str, Any]) -> str:
    """Render the download_url template for linux/amd64."""
    env = Environment(loader=BaseLoader())
    template = env.from_string(package_metadata["download_url"])
    render_kwargs: dict[str, Any] = {
        "os": "linux",
        "arch": "amd64",
        "rust_arch": "x86_64",
        "name": package_id,
    }
    for key, value in package_metadata.items():
        if key not in render_kwargs:
            render_kwargs[key] = value
    return template.render(**render_kwargs)
