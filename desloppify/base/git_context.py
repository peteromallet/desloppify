"""Read-only git observation with graceful degradation."""

from __future__ import annotations

import logging
import shutil
import subprocess  # nosec B404
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_GIT_TIMEOUT = 5


@dataclass(frozen=True)
class GitContext:
    available: bool
    branch: str | None = None
    head_sha: str | None = None
    has_uncommitted: bool = False
    root: str | None = None


def _run_git_command(*args: str) -> subprocess.CompletedProcess[str]:
    git_path = shutil.which("git")
    if not git_path:
        raise FileNotFoundError("git not found")
    return subprocess.run(  # nosec B603
        [git_path, *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    )


def detect_git_context() -> GitContext:
    """Detect current git context (branch, HEAD, uncommitted changes).

    Returns ``available=False`` when git is missing or not in a repo.
    """
    try:
        head = _run_git_command("rev-parse", "HEAD")
        if head.returncode != 0:
            return GitContext(available=False)

        sha = head.stdout.strip()[:12]

        branch_result = _run_git_command("rev-parse", "--abbrev-ref", "HEAD")
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None

        root_result = _run_git_command("rev-parse", "--show-toplevel")
        root = root_result.stdout.strip() if root_result.returncode == 0 else None

        status_result = _run_git_command("status", "--porcelain")
        has_uncommitted = bool(status_result.stdout.strip()) if status_result.returncode == 0 else False

        return GitContext(
            available=True,
            branch=branch,
            head_sha=sha,
            has_uncommitted=has_uncommitted,
            root=root,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("git context unavailable: %s", exc)
        return GitContext(available=False)


def update_pr_body(pr_number: int, body: str) -> bool:
    """Update PR description via ``gh pr edit``.  Returns True on success."""
    try:
        gh_path = shutil.which("gh")
        if not gh_path:
            raise FileNotFoundError("gh not found")
        result = subprocess.run(
            [gh_path, "pr", "edit", str(pr_number), "--body", body],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT * 3,
        )  # nosec B603
        if result.returncode != 0:
            logger.warning("gh pr edit failed: %s", result.stderr.strip())
            return False
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("gh pr edit unavailable: %s", exc)
        return False


__all__ = ["GitContext", "detect_git_context", "update_pr_body"]
