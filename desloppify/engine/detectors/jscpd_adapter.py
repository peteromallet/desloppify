"""Detect repeated code blocks via jscpd.

Replaces boilerplate_duplication.py with a thin adapter around jscpd
(https://github.com/kucherenko/jscpd), which uses proper per-language
tokenisation and supports type-2 clones (renamed identifiers).

Falls back gracefully to None when jscpd/npx is not installed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import signal
import subprocess  # nosec B404
import tempfile
from pathlib import Path

from desloppify.base.discovery.source import (

    collect_exclude_dirs,

    get_exclusions,

)
from desloppify.base.output.fallbacks import warn_best_effort

logger = logging.getLogger(__name__)

_BASE_IGNORES = (
    "**/node_modules/**",
    "**/.git/**",
    "**/__pycache__/**",
    "**/.venv*/**",
    "**/venv/**",
    "**/.desloppify/**",
    "**/.claude/**",
)

_ARTIFACT_PREFIXES = ("build/", "dist/", ".desloppify/", ".claude/")
_BUILD_MIRROR_PREFIX = "build/lib/"
_DEFAULT_JSCPD_TIMEOUT_SECONDS = 120


def _jscpd_timeout_seconds(default: int = _DEFAULT_JSCPD_TIMEOUT_SECONDS) -> int:
    """Return the jscpd timeout, allowing local long-scan overrides."""

    raw_timeout = os.environ.get("DESLOPPIFY_JSCPD_TIMEOUT_SECONDS")
    if raw_timeout is None:
        return default
    try:
        timeout = int(raw_timeout)
    except ValueError:
        warn_best_effort(
            "Ignoring invalid DESLOPPIFY_JSCPD_TIMEOUT_SECONDS value; "
            f"expected integer seconds, got {raw_timeout!r}."
        )
        return default
    return max(1, timeout)


def _to_scan_relative(path_resolved: Path, name: str) -> str | None:
    """Return scan-relative path, or None when file is outside scan path."""
    if not name:
        return None
    try:
        rel = Path(name).resolve().relative_to(path_resolved)
    except (ValueError, OSError):
        return None
    return str(rel).replace("\\", "/")


def _is_artifact_path(rel_path: str) -> bool:
    return rel_path.startswith(_ARTIFACT_PREFIXES)


def _is_build_mirror_pair(first_rel: str, second_rel: str) -> bool:
    if first_rel.startswith(_BUILD_MIRROR_PREFIX):
        return first_rel[len(_BUILD_MIRROR_PREFIX):] == second_rel
    if second_rel.startswith(_BUILD_MIRROR_PREFIX):
        return second_rel[len(_BUILD_MIRROR_PREFIX):] == first_rel
    return False


def _as_jscpd_globs(pattern: str) -> list[str]:
    raw = pattern.strip().replace("\\", "/").strip("/")
    if not raw:
        return []
    globs = [f"**/{raw}/**"]
    basename = raw.rsplit("/", 1)[-1]
    if "." in basename or "*" in basename:
        globs.append(f"**/{raw}")
    return globs


def _jscpd_ignore_arg(scan_path: Path) -> str:
    """Build jscpd ignore globs from defaults + runtime excludes."""
    patterns = set(_BASE_IGNORES)
    # Use collect_exclude_dirs for the directory-name portion, then convert
    # the remaining runtime globs (patterns with '*') to jscpd format.
    for dirname in collect_exclude_dirs(scan_path):
        base = Path(dirname).name
        patterns.update(_as_jscpd_globs(base))
    for pattern in get_exclusions():
        if "*" in pattern:
            patterns.update(_as_jscpd_globs(pattern))
    return ",".join(sorted(patterns))


def _parse_jscpd_report(report: dict, scan_path: Path) -> list[dict]:
    """Parse a jscpd JSON report dict and return clustered duplication entries.

    Clusters pairwise duplicates that share the same fragment into multi-file
    groups, producing the same output shape as the old boilerplate_duplication
    detector so that phase_boilerplate_duplication() needs no further changes.
    """
    duplicates = report.get("duplicates", [])
    if not duplicates:
        return []

    path_resolved = scan_path.resolve()

    # Cluster pairs by SHA256(fragment.strip()[:200])[:16]
    clusters: dict[str, dict] = {}

    for dup in duplicates:
        fragment = dup.get("fragment", "")
        fragment_key = hashlib.sha256(
            fragment.strip()[:200].encode("utf-8", errors="replace")
        ).hexdigest()[:16]

        first = dup.get("firstFile", {})
        second = dup.get("secondFile", {})
        first_name = first.get("name", "")
        second_name = second.get("name", "")

        first_rel = _to_scan_relative(path_resolved, first_name)
        second_rel = _to_scan_relative(path_resolved, second_name)
        if first_rel is None or second_rel is None:
            continue
        if (
            first_rel == second_rel
            or _is_artifact_path(first_rel)
            or _is_artifact_path(second_rel)
            or _is_build_mirror_pair(first_rel, second_rel)
        ):
            continue

        lines = dup.get("lines", 0)
        if fragment_key not in clusters:
            clusters[fragment_key] = {
                "id": fragment_key,
                "lines": lines,
                "fragment": fragment,
                "files": {},
            }

        cluster = clusters[fragment_key]
        for name, info in [(first_rel, first), (second_rel, second)]:
            if name not in cluster["files"]:
                cluster["files"][name] = info.get("start", 0)

    entries: list[dict] = []
    for cluster in clusters.values():
        files = cluster["files"]
        if len(files) < 2:
            continue
        locations = [
            {"file": f, "line": line}
            for f, line in sorted(files.items(), key=lambda kv: kv[0])
        ]
        entries.append(
            {
                "id": cluster["id"],
                "distinct_files": len(files),
                "window_size": cluster["lines"],
                "locations": locations,
                "sample": cluster["fragment"].splitlines()[:4],
            }
        )

    entries.sort(key=lambda e: (-e["distinct_files"], e["id"]))
    return entries


def _resolve_jscpd_command() -> list[str] | None:
    """Return the best available command prefix for running jscpd.

    Prefers a locally/globally installed ``jscpd`` executable over ``npx``.
    Returns ``None`` when neither ``jscpd`` nor ``npx`` can be found.
    """
    jscpd_path = shutil.which("jscpd")
    if jscpd_path:
        logger.debug("jscpd: using installed executable at %s", jscpd_path)
        return [jscpd_path]
    npx_path = shutil.which("npx")
    if npx_path:
        logger.debug("jscpd: falling back to npx at %s", npx_path)
        return [npx_path, "--yes", "jscpd"]
    return None


def _terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    """Best-effort termination for jscpd and descendants on timeout."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        return
    except (AttributeError, ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.kill()
    except OSError:
        return


def _run_jscpd_command(cmd: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    proc = subprocess.Popen(  # nosec B603
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(proc)
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr) from exc
    result = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    if proc.returncode:
        raise subprocess.CalledProcessError(
            proc.returncode,
            cmd,
            output=stdout,
            stderr=stderr,
        )
    return result


def detect_with_jscpd(path: Path) -> list[dict] | None:
    """Run jscpd on *path* and return duplication entries, or None on failure."""
    cmd_prefix = _resolve_jscpd_command()
    if cmd_prefix is None:
        warn_best_effort(
            "Boilerplate duplication detection skipped: jscpd/npx not found. "
            "Install with `npm install -g jscpd`."
        )
        logger.debug("jscpd: neither jscpd nor npx found — skipping")
        return None

    timeout_seconds = _jscpd_timeout_seconds()
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            _run_jscpd_command(
                [
                    *cmd_prefix,
                    str(path),
                    "--reporters",
                    "json",
                    "--output",
                    tmpdir,
                    "--min-lines",
                    "4",
                    "--min-tokens",
                    "50",
                    "--ignore",
                    _jscpd_ignore_arg(path),
                    "--silent",
                ],
                timeout=timeout_seconds,
            )
        except FileNotFoundError:
            warn_best_effort(
                "Boilerplate duplication detection skipped: jscpd/npx not found. "
                "Install with `npm install -g jscpd`."
            )
            logger.debug("jscpd: command not found at runtime — skipping")
            return None
        except subprocess.CalledProcessError as exc:
            warn_best_effort(
                "Boilerplate duplication detection skipped: jscpd exited with errors."
            )
            logger.debug(
                "jscpd: non-zero exit (%s): %s",
                exc.returncode,
                (exc.stderr or "").strip(),
            )
            return None
        except OSError as exc:
            warn_best_effort(
                "Boilerplate duplication detection skipped: jscpd failed to run."
            )
            logger.debug("jscpd: OS error running jscpd: %s", exc)
            return None
        except subprocess.TimeoutExpired:
            warn_best_effort(
                "Boilerplate duplication detection skipped: "
                f"jscpd timed out after {timeout_seconds}s."
            )
            logger.debug("jscpd: timed out")
            return None

        report_file = Path(tmpdir) / "jscpd-report.json"
        if not report_file.exists():
            logger.debug("jscpd: no report file produced — assuming no duplicates")
            return []

        try:
            report = json.loads(report_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            logger.debug("jscpd: failed to parse report: %s", exc)
            return None

        return _parse_jscpd_report(report, path)


__all__ = [
    "_parse_jscpd_report",
    "_resolve_jscpd_command",
    "_run_jscpd_command",
    "detect_with_jscpd",
]
