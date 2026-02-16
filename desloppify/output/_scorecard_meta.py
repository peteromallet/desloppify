"""Metadata helpers for scorecard rendering."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable


def resolve_project_name(project_root: Path) -> str:
    """Resolve owner/repo display name from GitHub CLI, git remote, or folder."""
    try:
        name = subprocess.check_output(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            cwd=str(project_root),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
        if "/" in name:
            return name
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        pass

    try:
        url = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=str(project_root),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
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
    ):
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
    except package_not_found_error:
        pass

    pyproject_path = project_root / "pyproject.toml"
    try:
        text = pyproject_path.read_text(encoding="utf-8")
        match = re.search(r'^\s*version\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
        if match:
            return match.group(1)
    except OSError:
        pass

    return "unknown"
