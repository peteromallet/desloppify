"""Ecosystem-specific framework presence detection (deterministic, evidence-based)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from desloppify.base.discovery.paths import get_project_root
from desloppify.languages._framework.base.types import LangRuntimeContract

from .registry import ensure_builtin_specs_loaded, list_framework_specs
from .types import DetectionConfig, EcosystemFrameworkDetection, FrameworkEvidence

_CACHE_PREFIX = "frameworks.ecosystem.present"


def _encode_detection(result: EcosystemFrameworkDetection) -> dict[str, Any]:
    return {
        "ecosystem": result.ecosystem,
        "package_root": str(result.package_root).replace("\\", "/"),
        "package_json_relpath": result.package_json_relpath,
        "present": result.present,
    }


def _decode_detection(payload: object) -> EcosystemFrameworkDetection | None:
    if not isinstance(payload, dict):
        return None
    eco = payload.get("ecosystem")
    package_root = payload.get("package_root")
    present = payload.get("present")
    package_json_relpath = payload.get("package_json_relpath")
    if not isinstance(eco, str) or not isinstance(package_root, str) or not isinstance(present, dict):
        return None
    return EcosystemFrameworkDetection(
        ecosystem=eco,
        package_root=Path(package_root),
        package_json_relpath=(str(package_json_relpath) if package_json_relpath is not None else None),
        present=present,
    )


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


def _node_framework_evidence(
    *,
    cfg: DetectionConfig,
    package_root: Path,
    project_root: Path,
    deps: set[str],
    dev_deps: set[str],
    scripts: list[str],
) -> tuple[bool, FrameworkEvidence]:
    dep_hits = tuple(sorted(set(cfg.dependencies).intersection(deps)))
    dev_dep_hits = tuple(sorted(set(cfg.dev_dependencies).intersection(dev_deps)))
    config_hits = _existing_relpaths(package_root, project_root, cfg.config_files, kind="file")
    marker_file_hits = _existing_relpaths(package_root, project_root, cfg.marker_files, kind="file")
    marker_dir_hits = _existing_relpaths(package_root, project_root, cfg.marker_dirs, kind="dir")

    script_hits: list[str] = []
    if scripts and cfg.script_pattern:
        pat = re.compile(cfg.script_pattern)
        script_hits = [s for s in scripts if pat.search(s)]

    # Presence is deterministic: deps/config/scripts imply presence. Marker dirs are context by default.
    present = bool(dep_hits or dev_dep_hits or config_hits or marker_file_hits or script_hits)
    if cfg.marker_dirs_imply_presence and marker_dir_hits:
        present = True

    evidence: FrameworkEvidence = {
        "dep_hits": list(dep_hits),
        "dev_dep_hits": list(dev_dep_hits),
        "config_hits": list(config_hits),
        "marker_file_hits": list(marker_file_hits),
        "marker_dir_hits": list(marker_dir_hits),
        "script_hits": script_hits[:5],
    }
    return present, evidence


def detect_ecosystem_frameworks(
    scan_path: Path,
    lang: LangRuntimeContract | None,
    ecosystem: str,
) -> EcosystemFrameworkDetection:
    """Detect framework presence for an ecosystem and scan path (cached per run)."""
    ensure_builtin_specs_loaded()
    eco = str(ecosystem or "").strip().lower()
    resolved_scan_path = Path(scan_path).resolve()
    cache_key = f"{_CACHE_PREFIX}:{eco}:{resolved_scan_path.as_posix()}"

    if lang is not None:
        cache = getattr(lang, "review_cache", None)
        if isinstance(cache, dict):
            cached = cache.get(cache_key)
            if isinstance(cached, EcosystemFrameworkDetection):
                return cached
            decoded = _decode_detection(cached)
            if decoded is not None:
                return decoded

    project_root = get_project_root()

    if eco != "node":
        result = EcosystemFrameworkDetection(
            ecosystem=eco,
            package_root=project_root,
            package_json_relpath=None,
            present={},
        )
        if lang is not None and isinstance(getattr(lang, "review_cache", None), dict):
            lang.review_cache[cache_key] = _encode_detection(result)
        return result

    package_json = _find_nearest_package_json(resolved_scan_path, project_root)
    package_root = (package_json.parent if package_json else project_root).resolve()
    payload = _read_package_json(package_json) if package_json else {}

    deps = _dep_set(payload, "dependencies") | _dep_set(payload, "peerDependencies") | _dep_set(
        payload, "optionalDependencies"
    )
    dev_deps = _dep_set(payload, "devDependencies")
    scripts = _script_values(payload)

    specs = list_framework_specs(ecosystem=eco)
    present: dict[str, FrameworkEvidence] = {}
    for framework_id, spec in specs.items():
        ok, evidence = _node_framework_evidence(
            cfg=spec.detection,
            package_root=package_root,
            project_root=project_root,
            deps=deps,
            dev_deps=dev_deps,
            scripts=scripts,
        )
        if ok:
            present[framework_id] = evidence

    # Apply mutual exclusions deterministically: present frameworks can suppress others.
    present_ids = set(present.keys())
    for framework_id, spec in specs.items():
        if framework_id not in present_ids:
            continue
        for excluded in spec.excludes:
            present.pop(str(excluded), None)

    result = EcosystemFrameworkDetection(
        ecosystem=eco,
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
        present=present,
    )

    if lang is not None:
        cache = getattr(lang, "review_cache", None)
        if isinstance(cache, dict):
            cache[cache_key] = _encode_detection(result)

    return result


__all__ = ["detect_ecosystem_frameworks"]
