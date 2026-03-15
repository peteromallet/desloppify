"""Tree-sitter phase factories for language plugins.

Each factory takes a ``TreeSitterLangSpec`` and returns a ``DetectorPhase``.
All phases resolve ``lang.file_finder`` at runtime.

Used by both generic plugins (via ``generic.py``) and full plugins (C#, Dart,
GDScript, TypeScript) that want tree-sitter-powered detection without
duplicating the phase construction logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from desloppify.base.output.terminal import log
from desloppify.engine._state.filtering import make_issue
from desloppify.languages._framework.base.smell_contracts import normalize_smell_matches
from desloppify.languages._framework.base.types import DetectorPhase
from desloppify.state_io import Issue

if TYPE_CHECKING:
    from desloppify.languages._framework.base.types import LangRuntimeContract
    from desloppify.languages._framework.treesitter import TreeSitterLangSpec

# ── Phase factories ────────────────────────────────────────


def make_ast_smells_phase(spec: TreeSitterLangSpec) -> DetectorPhase:
    """Create an AST smells phase: empty catches + unreachable code."""

    def run(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
        from desloppify.languages._framework.treesitter.analysis.smells import (
            detect_empty_catches,
            detect_unreachable_code,
        )

        file_list = lang.file_finder(path)
        issues: list[Issue] = []
        potentials: dict[str, int] = {}

        catches = normalize_smell_matches(
            detect_empty_catches(file_list, spec),
            content_key="type",
            default_content="catch",
        )
        for match in catches:
            issues.append(make_issue(
                "smells", match.file, f"empty_catch::{match.line}",
                tier=3, confidence="high",
                summary=f"Empty {match.content} — swallows errors silently",
            ))
        if catches:
            potentials["empty_catch"] = len(catches)
            log(f"         empty catch blocks: {len(catches)}")

        unreachable = normalize_smell_matches(
            detect_unreachable_code(file_list, spec),
            content_key="after",
            default_content="return",
        )
        for match in unreachable:
            issues.append(make_issue(
                "smells", match.file, f"unreachable_code::{match.line}",
                tier=3, confidence="high",
                summary=f"Unreachable code after {match.content}",
            ))
        if unreachable:
            potentials["unreachable_code"] = len(unreachable)
            log(f"         unreachable code: {len(unreachable)}")

        return issues, potentials

    return DetectorPhase("AST smells", run)


def make_cohesion_phase(spec: TreeSitterLangSpec) -> DetectorPhase:
    """Create a responsibility cohesion phase."""

    def run(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
        from desloppify.languages._framework.treesitter.analysis.cohesion import (
            detect_responsibility_cohesion,
        )

        file_list = lang.file_finder(path)
        issues: list[Issue] = []
        potentials: dict[str, int] = {}

        entries, checked = detect_responsibility_cohesion(file_list, spec)
        for e in entries:
            families = ", ".join(e["families"][:4])
            issues.append(make_issue(
                "responsibility_cohesion", e["file"],
                f"cohesion::{e['file']}",
                tier=3, confidence="medium",
                summary=(
                    f"{e['component_count']} disconnected function clusters "
                    f"({e['function_count']} functions) — likely mixed responsibilities"
                ),
                detail={
                    "cluster_count": e["component_count"],
                    "family": families,
                    "families": e["families"],
                },
            ))
        if entries:
            potentials["responsibility_cohesion"] = len(entries)
            log(f"         low-cohesion files: {len(entries)}")

        return issues, potentials

    return DetectorPhase("Responsibility cohesion", run)


def make_unused_imports_phase(spec: TreeSitterLangSpec) -> DetectorPhase:
    """Create an unused imports phase."""

    def run(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
        from desloppify.languages._framework.treesitter.analysis.unused_imports import (
            detect_unused_imports,
        )

        file_list = lang.file_finder(path)
        issues: list[Issue] = []
        potentials: dict[str, int] = {}

        entries = detect_unused_imports(file_list, spec)
        for e in entries:
            symbol = e.get("symbol")
            issue_name = f"unused_import::{e['line']}" + (f"::{symbol}" if symbol else "")
            issues.append(make_issue(
                "unused", e["file"], issue_name,
                tier=3, confidence="medium",
                summary=f"Unused import: {e['name']}",
            ))
        if entries:
            potentials["unused_imports"] = len(entries)
            log(f"         unused imports: {len(entries)}")

        return issues, potentials

    return DetectorPhase("Unused imports", run)


# ── Convenience: all tree-sitter phases for a named language ──


def all_treesitter_phases(spec_name: str) -> list[DetectorPhase]:
    """Return all tree-sitter-powered phases for a language plugin.

    Convenience bundle — returns AST smells, cohesion, and (when import
    query exists) unused imports.  Returns [] if tree-sitter-language-pack
    is not installed.
    """
    from desloppify.languages._framework.treesitter import get_spec, is_available

    if not is_available():
        return []

    spec = get_spec(spec_name)
    if spec is None or not spec.function_query:
        return []

    phases = [
        make_ast_smells_phase(spec),
        make_cohesion_phase(spec),
    ]

    if spec.import_query:
        phases.append(make_unused_imports_phase(spec))

    return phases


__all__ = [
    "all_treesitter_phases",
    "make_ast_smells_phase",
    "make_cohesion_phase",
    "make_unused_imports_phase",
]
