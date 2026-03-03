from datetime import UTC, datetime
import os
import shutil
import subprocess

from dotenv import load_dotenv
from invoke.tasks import task

load_dotenv()


def resolve_registry(registry: str | None) -> str:
    if registry:
        return registry

    env_registry = os.getenv("CONTAINER_REGISTRY")
    if env_registry:
        return env_registry

    github_repo = os.getenv("GITHUB_REPOSITORY")
    if github_repo:
        return f"ghcr.io/{github_repo}"

    # Local fallback: build a non-registry image name
    return "tools"


def resolve_tag(tag: str | None) -> str:
    if tag:
        return tag

    github_sha = os.getenv("GITHUB_SHA")
    if github_sha:
        return github_sha

    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def should_push(push_flag: bool) -> bool:
    return push_flag


def resolve_container_runtime() -> str:
    if shutil.which("podman"):
        return "podman"
    if shutil.which("docker"):
        return "docker"
    raise RuntimeError("Neither podman nor docker is available in PATH.")


@task
def container(
    c,
    registry: str | None = None,
    tag: str | None = None,
    push: bool = False,
) -> None:
    """Build container image with configurable registry and tag."""
    registry = resolve_registry(registry)
    tag = resolve_tag(tag)

    image = f"{registry}:{tag}"

    runtime = resolve_container_runtime()

    print(f"Using container runtime: {runtime}")

    # Attempt to pull existing image for layer reuse (non-fatal if missing)
    c.run(f"{runtime} pull {image} || true", warn=True, echo=True)

    created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    github_repo = os.getenv("GITHUB_REPOSITORY")
    source = f"https://github.com/{github_repo}" if github_repo else ""

    labels = [
        '--label org.opencontainers.image.title="tools"',
        '--label org.opencontainers.image.description="Curated CLI toolchain container image"',
        f'--label org.opencontainers.image.url="{source}"',
        f'--label org.opencontainers.image.source="{source}"',
        f'--label org.opencontainers.image.revision="{tag}"',
        f'--label org.opencontainers.image.created="{created}"',
        '--label org.opencontainers.image.licenses="MIT"',
    ]

    label_args = " ".join(labels)

    c.run(f"{runtime} build -t {image} {label_args} .", echo=True)

    if not should_push(push):
        return

    github_actor = os.getenv("GITHUB_ACTOR")
    github_token = os.getenv("GITHUB_TOKEN")

    if github_actor and github_token and runtime == "podman":
        c.run(
            f"echo {github_token} | {runtime} login ghcr.io -u {github_actor} --password-stdin",
            echo=True,
        )

    c.run(f"{runtime} push {image}", echo=True)

    if os.getenv("GITHUB_REF") == "refs/heads/main":
        latest_image = f"{registry}:latest"
        c.run(f"{runtime} tag {image} {latest_image}", echo=True)
        c.run(f"{runtime} push {latest_image}", echo=True)
