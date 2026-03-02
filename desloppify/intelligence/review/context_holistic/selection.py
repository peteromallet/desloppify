"""File selection and context section builders for holistic review."""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path

from desloppify.core.discovery_api import rel, resolve_path
from desloppify.engine.policy.zones import EXCLUDED_ZONE_VALUES
from desloppify.intelligence.review._context.patterns import (
    ERROR_PATTERNS as _ERROR_PATTERNS,
)
from desloppify.intelligence.review._context.patterns import (
    FUNC_NAME_RE as _FUNC_NAME_RE,
)
from desloppify.intelligence.review._context.patterns import (
    extract_imported_names as _extract_imported_names,
)
from desloppify.intelligence.review.context import file_excerpt, importer_count

logger = logging.getLogger(__name__)


def select_holistic_files(path: Path, lang: object, files: list[str] | None) -> list[str]:
    selected = files if files is not None else (lang.file_finder(path) if lang.file_finder else [])
    if not selected:
        return []

    zone_map = getattr(lang, "zone_map", None)
    if zone_map is None:
        return selected

    filtered: list[str] = []
    for filepath in selected:
        try:
            zone = zone_map.get(filepath)
            zone_value = getattr(zone, "value", str(zone))
        except (AttributeError, KeyError, TypeError, ValueError):
            zone_value = "production"
        if zone_value in EXCLUDED_ZONE_VALUES:
            continue
        filtered.append(filepath)
    return filtered


def _architecture_context(lang, file_contents: dict[str, str]) -> dict:
    arch: dict = {}
    if not lang.dep_graph:
        return arch

    importer_counts = {}
    for filepath, entry in lang.dep_graph.items():
        entry_importer_count = importer_count(entry)
        if entry_importer_count > 0:
            importer_counts[rel(filepath)] = entry_importer_count
    top_imported = sorted(importer_counts.items(), key=lambda item: -item[1])[:10]
    arch["god_modules"] = [
        {"file": filepath, "importers": count, "excerpt": file_excerpt(filepath) or ""}
        for filepath, count in top_imported
        if count >= 5
    ]
    arch["top_imported"] = dict(top_imported)
    return arch


def _coupling_context(file_contents: dict[str, str]) -> dict:
    coupling: dict = {}
    module_level_io = []
    for filepath, content in file_contents.items():
        for idx, raw_line in enumerate(content.splitlines()[:50]):
            stripped = raw_line.strip()
            if stripped.startswith(
                ("def ", "class ", "async def ", "if ", "#", "@", "import ", "from ")
            ):
                continue
            if re.search(
                r"\b(?:open|connect|requests?\.|urllib|subprocess|os\.system)\b",
                stripped,
            ):
                module_level_io.append(
                    {
                        "file": rel(filepath),
                        "line": idx + 1,
                        "code": stripped[:100],
                    }
                )
    if module_level_io:
        coupling["module_level_io"] = module_level_io[:20]
    return coupling


def _naming_conventions_context(file_contents: dict[str, str]) -> dict:
    dir_styles: dict[str, Counter] = {}
    for filepath, content in file_contents.items():
        parts = Path(filepath).parts
        if len(parts) < 2:
            continue
        dir_name = parts[-2] + "/"
        counter = dir_styles.setdefault(dir_name, Counter())
        for name in _FUNC_NAME_RE.findall(content):
            if "_" in name and name.islower():
                counter["snake_case"] += 1
            elif name[0].islower() and any(ch.isupper() for ch in name):
                counter["camelCase"] += 1
            elif name[0].isupper():
                counter["PascalCase"] += 1
    return {
        name: dict(counter.most_common(3))
        for name, counter in dir_styles.items()
        if sum(counter.values()) >= 3
    }


def _sibling_behavior_context(
    file_contents: dict[str, str], *, base_path: Path | str | None = None
) -> dict:
    root = Path(base_path).resolve() if base_path is not None else None

    _BOILERPLATE_NAMES = frozenset({
        "__init__.py", "conftest.py", "setup.py", "__main__.py",
    })

    def _bucket_for(filepath: str) -> str | None:
        if Path(filepath).name in _BOILERPLATE_NAMES:
            return None
        target = Path(filepath).resolve()
        if root is not None:
            try:
                parts = target.relative_to(root).parts
                if len(parts) >= 2:
                    return "/".join(parts[:-1]) + "/"
                return None
            except ValueError:
                logger.debug("Path %s not relative to root %s, using fallback bucket", filepath, root)
        parts = Path(filepath).parts
        if len(parts) < 2:
            return None
        return f"{parts[-2]}/"

    def _display_path(filepath: str) -> str:
        target = Path(filepath).resolve()
        if root is not None:
            try:
                return target.relative_to(root).as_posix()
            except ValueError:
                logger.debug("Path %s not relative to root %s, using rel() fallback", filepath, root)
        return rel(filepath)

    dir_imports: dict[str, dict[str, set[str]]] = {}
    for filepath, content in file_contents.items():
        dir_name = _bucket_for(filepath)
        if dir_name is None:
            continue
        file_rel = _display_path(filepath)
        dir_imports.setdefault(dir_name, {})[file_rel] = _extract_imported_names(content)

    sibling_behavior: dict = {}
    for dir_name, file_names_map in dir_imports.items():
        total = len(file_names_map)
        if total < 3:
            continue
        name_counts: Counter = Counter()
        for names in file_names_map.values():
            for name in names:
                name_counts[name] += 1
        threshold = total * 0.6
        shared = {
            name: count for name, count in name_counts.items() if count >= threshold
        }
        if not shared:
            continue
        outliers = []
        for file_rel, names in file_names_map.items():
            missing = [name for name in shared if name not in names]
            if missing:
                outliers.append({"file": file_rel, "missing": sorted(missing)})
        if not outliers:
            continue
        sibling_behavior[dir_name] = {
            "shared_patterns": {
                name: {"count": count, "total": total}
                for name, count in sorted(shared.items(), key=lambda item: -item[1])
            },
            "outliers": sorted(
                outliers, key=lambda item: len(item["missing"]), reverse=True
            ),
        }
    return sibling_behavior


def _error_strategy_context(file_contents: dict[str, str]) -> dict:
    dir_errors: dict[str, Counter] = {}
    for filepath, content in file_contents.items():
        parts = Path(filepath).parts
        if len(parts) < 2:
            continue
        dir_name = parts[-2] + "/"
        counter = dir_errors.setdefault(dir_name, Counter())
        for pattern_name, pattern in _ERROR_PATTERNS.items():
            matches = pattern.findall(content)
            if matches:
                counter[pattern_name] += len(matches)
    return {
        name: dict(counter.most_common(5))
        for name, counter in dir_errors.items()
        if sum(counter.values()) >= 2
    }


def _in_allowed_files(filepath: object, allowed_files: set[str] | None) -> bool:
    if allowed_files is None:
        return True
    return isinstance(filepath, str) and filepath in allowed_files


def _dependencies_context(
    state: dict,
    *,
    allowed_files: set[str] | None = None,
) -> dict:
    cycle_findings = []
    findings = state.get("findings", {})
    if not isinstance(findings, dict):
        findings = {}
    for finding in findings.values():
        if not isinstance(finding, dict):
            continue
        if finding.get("detector") != "cycles" or finding.get("status") != "open":
            continue
        if not _in_allowed_files(finding.get("file", ""), allowed_files):
            continue
        cycle_findings.append(finding)
    if not cycle_findings:
        return {}
    return {
        "existing_cycles": len(cycle_findings),
        "cycle_summaries": [finding["summary"][:120] for finding in cycle_findings[:10]],
    }


def _testing_context(
    lang,
    state: dict,
    file_contents: dict[str, str],
    *,
    allowed_files: set[str] | None = None,
) -> dict:
    testing: dict = {"total_files": len(file_contents)}
    if not lang.dep_graph:
        return testing

    tc_findings = {
        finding["file"]
        for finding in state.get("findings", {}).values()
        if finding.get("detector") == "test_coverage"
        and finding.get("status") == "open"
        and _in_allowed_files(finding.get("file", ""), allowed_files)
    }
    if not tc_findings:
        return testing

    critical_untested = []
    for filepath in tc_findings:
        entry = lang.dep_graph.get(resolve_path(filepath), {})
        entry_importer_count = importer_count(entry)
        if entry_importer_count >= 3:
            critical_untested.append(
                {"file": filepath, "importers": entry_importer_count}
            )
    testing["critical_untested"] = sorted(
        critical_untested,
        key=lambda item: -item["importers"],
    )[:10]
    return testing


def _api_surface_context(lang, file_contents: dict[str, str]) -> dict:
    api_surface_fn = getattr(lang, "review_api_surface_fn", None)
    if not callable(api_surface_fn):
        return {}
    computed = api_surface_fn(file_contents)
    return computed if isinstance(computed, dict) else {}
