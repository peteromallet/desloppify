"""Generic framework detection for TypeScript projects."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from desloppify.base.discovery.paths import get_project_root
from desloppify.languages._framework.base.types import LangRuntimeContract

from .catalog import TS_FRAMEWORK_SIGNATURES, FrameworkSignature
from .types import FrameworkCandidate, FrameworkId, PrimaryFrameworkDetection

_CACHE_KEY = "framework.typescript.primary"


def _find_nearest_package_json(scan_path: Path, project_root: Path) -> Path | None:
    resolved = scan_path if scan_path.is_absolute() else (project_root / scan_path)
    resolved = resolved.resolve()
    if resolved.is_file():
        resolved = resolved.parent

    # If scan_path is inside runtime project root, cap traversal there.
    # Otherwise (e.g. --path /tmp/other-repo), traverse from scan_path upward.
    limit_to_project_root = False
    try:
        resolved.relative_to(project_root)
        limit_to_project_root = True
    except ValueError:
        limit_to_project_root = False

    cur = resolved
    while True:
        candidate = cur / "package.json"
        if candidate.is_file():
            return candidate
        if (limit_to_project_root and cur == project_root) or cur.parent == cur:
            break
        cur = cur.parent

    # Fallback only when no package.json exists in the scanned tree.
    candidate = project_root / "package.json"
    return candidate if candidate.is_file() else None


def _read_package_json(package_json: Path) -> dict[str, Any]:
    try:
        payload = json.loads(package_json.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _dep_set(payload: dict[str, Any], key: str) -> set[str]:
    deps = payload.get(key)
    if not isinstance(deps, dict):
        return set()
    return {str(k) for k in deps.keys()}


def _script_values(payload: dict[str, Any]) -> list[str]:
    scripts = payload.get("scripts")
    if not isinstance(scripts, dict):
        return []
    return [v for v in scripts.values() if isinstance(v, str)]


def _existing_relpaths(
    package_root: Path,
    project_root: Path,
    candidates: tuple[str, ...],
    *,
    kind: str,
) -> tuple[str, ...]:
    hits: list[str] = []
    for relpath in candidates:
        path = (package_root / relpath).resolve()
        ok = path.is_dir() if kind == "dir" else path.is_file()
        if not ok:
            continue
        try:
            hits.append(path.relative_to(project_root).as_posix())
        except ValueError:
            hits.append(path.as_posix())
    return tuple(hits)


def _score_signature(
    sig: FrameworkSignature,
    *,
    package_root: Path,
    project_root: Path,
    deps: set[str],
    dev_deps: set[str],
    scripts: list[str],
) -> FrameworkCandidate:
    dep_hits = tuple(sorted(set(sig.dependencies).intersection(deps)))
    dev_dep_hits = tuple(sorted(set(sig.dev_dependencies).intersection(dev_deps)))
    config_hits = _existing_relpaths(package_root, project_root, sig.config_files, kind="file")
    marker_file_hits = _existing_relpaths(package_root, project_root, sig.marker_files, kind="file")
    marker_dir_hits = _existing_relpaths(package_root, project_root, sig.marker_dirs, kind="dir")

    score = 0
    score += sig.weight_dependency if (dep_hits or dev_dep_hits) else 0
    score += sig.weight_config if config_hits else 0
    score += sig.weight_marker if (marker_file_hits or marker_dir_hits) else 0

    script_hits: list[str] = []
    if scripts:
        if sig.id == "nextjs":
            pat = re.compile(r"(?:^|\s)next(?:\s|$)")
        elif sig.id == "vite":
            pat = re.compile(r"(?:^|\s)vite(?:\s|$)")
        else:
            pat = None
        if pat is not None:
            script_hits = [s for s in scripts if pat.search(s)]
            if script_hits:
                score += sig.weight_script

    evidence: dict[str, Any] = {
        "dep_hits": list(dep_hits),
        "dev_dep_hits": list(dev_dep_hits),
        "config_hits": list(config_hits),
        "marker_file_hits": list(marker_file_hits),
        "marker_dir_hits": list(marker_dir_hits),
        "script_hits": script_hits[:5],
    }

    if sig.id == "nextjs":
        evidence["app_roots"] = [
            p for p in marker_dir_hits if p.endswith("/app") or p == "app"
        ]
        evidence["pages_roots"] = [
            p for p in marker_dir_hits if p.endswith("/pages") or p == "pages"
        ]

    return FrameworkCandidate(
        id=sig.id,
        label=sig.label,
        score=score,
        evidence=evidence,
    )


def detect_primary_ts_framework(
    scan_path: Path,
    lang: LangRuntimeContract | None = None,
    *,
    signatures: tuple[FrameworkSignature, ...] = TS_FRAMEWORK_SIGNATURES,
) -> PrimaryFrameworkDetection:
    """Detect the primary TS framework for this scan path (cached per run)."""
    cache_key = f"{_CACHE_KEY}:{Path(scan_path).resolve().as_posix()}"
    if lang is not None:
        cache = getattr(lang, "review_cache", None)
        if isinstance(cache, dict):
            cached = cache.get(cache_key)
            if isinstance(cached, PrimaryFrameworkDetection):
                return cached

    project_root = get_project_root()
    package_json = _find_nearest_package_json(scan_path, project_root)
    package_root = (package_json.parent if package_json else project_root).resolve()
    payload = _read_package_json(package_json) if package_json else {}

    deps = _dep_set(payload, "dependencies") | _dep_set(payload, "peerDependencies") | _dep_set(
        payload, "optionalDependencies"
    )
    dev_deps = _dep_set(payload, "devDependencies")
    scripts = _script_values(payload)

    candidates = tuple(
        _score_signature(
            sig,
            package_root=package_root,
            project_root=project_root,
            deps=deps,
            dev_deps=dev_deps,
            scripts=scripts,
        )
        for sig in signatures
    )
    ordered = sorted(candidates, key=lambda c: (-c.score, c.label))

    primary_id: FrameworkId | None = None
    primary_score = 0
    if ordered and ordered[0].score > 0:
        sig = next((s for s in signatures if s.id == ordered[0].id), None)
        threshold = sig.primary_score_threshold if sig is not None else 5
        if ordered[0].score >= threshold:
            primary_id = ordered[0].id
            primary_score = ordered[0].score

    result = PrimaryFrameworkDetection(
        package_root=package_root,
        package_json_relpath=(
            (
                package_json.relative_to(project_root).as_posix()
                if package_json and package_json.is_relative_to(project_root)
                else package_json.as_posix()
            )
            if package_json
            else None
        ),
        primary_id=primary_id,
        primary_score=primary_score,
        candidates=tuple(ordered),
    )

    if lang is not None:
        cache = getattr(lang, "review_cache", None)
        if isinstance(cache, dict):
            cache[cache_key] = result

    return result


__all__ = ["detect_primary_ts_framework"]
