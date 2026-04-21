from contextlib import contextmanager
import subprocess

from dotenv import load_dotenv

load_dotenv()


class AutomationError(Exception):
    """Base exception for automation errors."""


class GitHubRateLimitError(AutomationError):
    """GitHub API rate limit exceeded."""


class GitOperationError(AutomationError):
    """Git operation failed."""

    def __init__(self, command: tuple[str, ...] | list[str], stderr: str):
        self.command = command
        self.stderr = stderr
        super().__init__(f"Git command failed: {' '.join(command)}\n{stderr}")


def safe_git_command(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run git command with proper error handling."""
    try:
        return subprocess.run(
            ["git"] + list(args),
            capture_output=True,
            text=True,
            check=check,
        )
    except subprocess.CalledProcessError as e:
        raise GitOperationError(args, e.stderr) from e


@contextmanager
def ensure_clean_checkout():
    """Ensure we return to original git branch after operations."""
    try:
        result = safe_git_command("rev-parse", "--abbrev-ref", "HEAD")
        original_branch = result.stdout.strip()
    except GitOperationError:
        original_branch = None

    try:
        yield
    finally:
        if original_branch:
            safe_git_command("checkout", original_branch, check=False)
