"""Metadata helpers for scorecard rendering."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess  # nosec B404
from collections.abc import Callable
from pathlib import Path

from desloppify.base.output.fallbacks import log_best_effort_failure

logger = logging.getLogger(__name__)


def resolve_project_name(project_root: Path) -> str:
    """Resolve owner/repo display name from GitHub CLI, git remote, or folder."""
    try:
        gh_path = shutil.which("gh")
        if gh_path is None:
            raise FileNotFoundError("gh not found")
        name = subprocess.check_output(
            [
                gh_path,
                "repo",
                "view",
                "--json",
                "nameWithOwner",
                "-q",
                ".nameWithOwner",
            ],
            cwd=str(project_root),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()  # nosec B603
        if "/" in name:
            return name
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ) as exc:
        logger.debug("gh repo view failed, falling back to git remote: %s", exc)

    try:
        git_path = shutil.which("git")
        if git_path is None:
            raise FileNotFoundError("git not found")
        url = subprocess.check_output(
            [git_path, "config", "--get", "remote.origin.url"],
            cwd=str(project_root),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()  # nosec B603
        if url.startswith("git@") and ":" in url:
            path = url.split(":")[-1]
        else:
            path = "/".join(url.split("/")[-2:])
        return path.removesuffix(".git")
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        IndexError,
        subprocess.TimeoutExpired,
    ) as exc:
        logger.debug("git remote lookup failed, falling back to folder name: %s", exc)
        return project_root.name


def resolve_package_version(
    project_root: Path,
    *,
    version_getter: Callable[[str], str],
    package_not_found_error: type[Exception],
) -> str:
    """Resolve package version from installed metadata or local pyproject."""
    try:
        return version_getter("desloppify")
    except package_not_found_error as exc:
        log_best_effort_failure(logger, "read package metadata version", exc)

    pyproject_path = project_root / "pyproject.toml"
    try:
        text = pyproject_path.read_text(encoding="utf-8")
        match = re.search(r'^\s*version\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
        if match:
            return match.group(1)
    except OSError as exc:
        log_best_effort_failure(logger, "read pyproject.toml for package version", exc)

    return "unknown"
