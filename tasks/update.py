from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse

from invoke.tasks import task
from jinja2 import Environment, FileSystemLoader, select_autoescape
from jsonschema import validate
import requests
import semver

from tasks.lib import METADATA_FILE, METADATA_SCHEMA_FILE, load_metadata

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


def get_owner_and_repo(url: str):
    if url.startswith("git@"):
        try:
            path = url.split(":", 1)[1]
            if path.endswith(".git"):
                path = path[:-4]
            owner, repo = path.split("/", 1)
            return owner, repo
        except Exception:
            return None, None
    try:
        parsed = urlparse(url)
        path = parsed.path.lstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        owner, repo = path.split("/", 1)
        return owner, repo
    except Exception:
        return None, None


def get_latest_github_release_version(owner: str, repo: str) -> str | None:
    if not owner or not repo:
        return None

    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code != 200:
        return None

    data = response.json()
    return data.get("tag_name")


def detect_updates(metadata: dict) -> list[dict]:
    updates = []

    for name, package_metadata in metadata.items():
        current_version = package_metadata.get("version")
        repo_url = package_metadata.get("repo_url")

        owner, repo = get_owner_and_repo(repo_url)
        if not owner or not repo:
            continue
        latest_tag = get_latest_github_release_version(owner, repo)

        match = re.search(r"v?(\d+\.\d+\.\d+)", latest_tag or "")
        if not match:
            continue

        latest_version = match.group(1)

        try:
            if semver.compare(current_version, latest_version) == -1:
                updates.append(
                    {
                        "package": name,
                        "from_version": current_version,
                        "to_version": latest_version,
                    }
                )
        except ValueError:
            continue

    return updates


@task(aliases=["a", "all"])
def update_all(c, dry_run: bool = False) -> None:
    metadata = load_metadata()
    updates = detect_updates(metadata)

    if not updates:
        print(json.dumps([], indent=2))
        return

    if dry_run:
        print(json.dumps(updates, indent=2))
        raise SystemExit(1)

    for update in updates:
        metadata[update["package"]]["version"] = update["to_version"]

    write_metadata(metadata)

    print(json.dumps(updates, indent=2))


@task(aliases=["p"])
def package(c, name: str, dry_run: bool = False) -> None:
    metadata = load_metadata()

    if name not in metadata:
        print(json.dumps([], indent=2))
        return

    single = {name: metadata[name]}
    updates = detect_updates(single)

    if not updates:
        print(json.dumps([], indent=2))
        return

    if dry_run:
        print(json.dumps(updates, indent=2))
        raise SystemExit(1)

    metadata[name]["version"] = updates[0]["to_version"]
    write_metadata(metadata)

    print(json.dumps(updates, indent=2))


@task
def add(
    c,
    repo_url: str,
    download_url: str,
    license: str,
    description: str,
    name: str | None = None,
    dry_run: bool = False,
) -> None:
    metadata = load_metadata()

    owner, repo = get_owner_and_repo(repo_url)
    if not owner or not repo:
        raise ValueError("Unable to determine owner/repo from repo_url")

    inferred_name = repo.lower()
    package_name = name or inferred_name

    if package_name in metadata:
        raise ValueError(f"Package '{package_name}' already exists")

    latest_tag = get_latest_github_release_version(owner, repo)
    if not latest_tag:
        raise ValueError("Unable to determine latest release version")

    match = re.search(r"v?(\d+\.\d+\.\d+)", latest_tag)
    if not match:
        raise ValueError(f"Unable to extract semver from tag '{latest_tag}'")

    version = match.group(1)

    metadata[package_name] = {
        "description": description,
        "download_url": download_url,
        "repo_url": repo_url,
        "license": license,
        "version": version,
    }

    metadata = dict(sorted(metadata.items(), key=lambda item: item[0]))

    if dry_run:
        print(json.dumps({package_name: metadata[package_name]}, indent=2))
        return

    write_metadata(metadata)

    print(
        json.dumps(
            {
                "package": package_name,
                "version": version,
            },
            indent=2,
        )
    )


@task
def automation(c, ci: bool = False, dry_run: bool = False) -> None:
    """
    Run full update automation:
    - Run update.update-all
    - Create branch
    - Commit metadata
    - Create PR
    - Enable auto-merge (CI only)
    """

    metadata = load_metadata()
    updates = detect_updates(metadata)

    if not updates:
        print("No updates found.")
        return

    branch_name = f"automation/update-{datetime.utcnow().strftime('%Y%m%d')}"

    if dry_run:
        print("Dry run mode enabled.")
        print(json.dumps(updates, indent=2))
        print(f"Would create branch: {branch_name}")
        print("Would commit: chore: update packages")
        print(f"Would create PR targeting 'main' with {len(updates)} update(s).")
        return

    for update in updates:
        metadata[update["package"]]["version"] = update["to_version"]

    write_metadata(metadata)

    # Checkout existing branch or create a new one
    branch_exists = subprocess.run(
        ["git", "branch", "--list", branch_name],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    if branch_exists:
        subprocess.run(["git", "checkout", branch_name], check=True)
    else:
        subprocess.run(["git", "checkout", "-b", branch_name], check=True)

    subprocess.run(["git", "add", str(METADATA_FILE)], check=True)
    subprocess.run(["git", "commit", "-m", "chore: update packages"], check=True)
    subprocess.run(["git", "push", "-u", "origin", branch_name], check=True)

    count = len(updates)

    if count <= 3:
        parts = [f"{u['package']} ({u['from_version']} → {u['to_version']})" for u in updates]
        title = f"chore: update {', '.join(parts)}"
    else:
        first = ", ".join(u["package"] for u in updates[:3])
        title = f"chore: update {first} +{count - 3} more"

    pretty_json = json.dumps(updates, indent=2)

    body = (
        "Automated weekly package updates.\n\n"
        f"{count} package(s) updated.\n\n"
        "<details>\n"
        "<summary>Updated Packages (click to expand)</summary>\n\n"
        "```json\n"
        f"{pretty_json}\n"
        "```\n\n"
        "</details>"
    )

    # Check for existing open PR
    pr_check = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--head",
            branch_name,
            "--state",
            "open",
            "--json",
            "number,url",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    existing_prs = json.loads(pr_check.stdout) if pr_check.stdout.strip() else []

    if existing_prs:
        pr_number = str(existing_prs[0]["number"])
        print(f"Reusing existing PR: {existing_prs[0]['url']}")
    else:
        subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--body",
                body,
                "--head",
                branch_name,
                "--base",
                "main",
            ],
            check=True,
        )
        pr_number = subprocess.check_output(
            ["gh", "pr", "view", "--json", "number", "--jq", ".number"],
            text=True,
        ).strip()

    # Add dependencies label (ignore failure if label does not exist)
    subprocess.run(
        ["gh", "pr", "edit", pr_number, "--add-label", "dependencies"],
        check=False,
    )

    # Enable auto-merge (respects branch protection rules)
    subprocess.run(
        ["gh", "pr", "merge", pr_number, "--auto", "--squash"],
        check=False,
    )
