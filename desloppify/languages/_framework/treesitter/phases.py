"""Tree-sitter phase factories for language plugins.

Each factory takes a ``TreeSitterLangSpec`` and returns a ``DetectorPhase``.
All phases resolve ``lang.file_finder`` at runtime.

Used by both generic plugins (via ``generic.py``) and full plugins (C#, Dart,
GDScript, TypeScript) that want tree-sitter-powered detection without
duplicating the phase construction logic.
"""

from __future__ import annotations

from desloppify.languages._framework.base.types import DetectorPhase
from desloppify.state import make_finding
from desloppify.utils import log


# ── Phase factories ────────────────────────────────────────


def make_ast_smells_phase(spec) -> DetectorPhase:
    """Create an AST smells phase: empty catches + unreachable code."""

    def run(path, lang):
        from desloppify.languages._framework.treesitter._smells import (
            detect_empty_catches,
            detect_unreachable_code,
        )

        file_list = lang.file_finder(path)
        findings = []
        potentials: dict[str, int] = {}

        catches = detect_empty_catches(file_list, spec)
        for e in catches:
            findings.append(make_finding(
                "smells", e["file"], f"empty_catch::{e['line']}",
                tier=3, confidence="high",
                summary=f"Empty {e['type']} — swallows errors silently",
            ))
        if catches:
            potentials["empty_catch"] = len(catches)
            log(f"         empty catch blocks: {len(catches)}")

        unreachable = detect_unreachable_code(file_list, spec)
        for e in unreachable:
            findings.append(make_finding(
                "smells", e["file"], f"unreachable_code::{e['line']}",
                tier=3, confidence="high",
                summary=f"Unreachable code after {e['after']}",
            ))
        if unreachable:
            potentials["unreachable_code"] = len(unreachable)
            log(f"         unreachable code: {len(unreachable)}")

        return findings, potentials

    return DetectorPhase("AST smells", run)


def make_cohesion_phase(spec) -> DetectorPhase:
    """Create a responsibility cohesion phase."""

    def run(path, lang):
        from desloppify.languages._framework.treesitter._cohesion import (
            detect_responsibility_cohesion,
        )

        file_list = lang.file_finder(path)
        findings = []
        potentials: dict[str, int] = {}

        entries, checked = detect_responsibility_cohesion(file_list, spec)
        for e in entries:
            families = ", ".join(e["families"][:4])
            findings.append(make_finding(
                "responsibility_cohesion", e["file"],
                f"cohesion::{e['file']}",
                tier=3, confidence="medium",
                summary=(
                    f"{e['component_count']} disconnected function clusters "
                    f"({e['function_count']} functions) — likely mixed responsibilities"
                ),
                detail=f"Clusters: {families}",
            ))
        if entries:
            potentials["responsibility_cohesion"] = len(entries)
            log(f"         low-cohesion files: {len(entries)}")

        return findings, potentials

    return DetectorPhase("Responsibility cohesion", run)


def make_unused_imports_phase(spec) -> DetectorPhase:
    """Create an unused imports phase."""

    def run(path, lang):
        from desloppify.languages._framework.treesitter._unused_imports import (
            detect_unused_imports,
        )

        file_list = lang.file_finder(path)
        findings = []
        potentials: dict[str, int] = {}

        entries = detect_unused_imports(file_list, spec)
        for e in entries:
            findings.append(make_finding(
                "unused", e["file"], f"unused_import::{e['line']}",
                tier=3, confidence="medium",
                summary=f"Unused import: {e['name']}",
            ))
        if entries:
            potentials["unused_imports"] = len(entries)
            log(f"         unused imports: {len(entries)}")

        return findings, potentials

    return DetectorPhase("Unused imports", run)


# ── Convenience: all tree-sitter phases for a named language ──


def all_treesitter_phases(spec_name: str) -> list[DetectorPhase]:
    """Return all tree-sitter-powered phases for a language plugin.

    Convenience bundle — returns AST smells, cohesion, and (when import
    query exists) unused imports.  Returns [] if tree-sitter-language-pack
    is not installed.
    """
    from desloppify.languages._framework.treesitter import is_available

    if not is_available():
        return []

    from desloppify.languages._framework.treesitter._specs import TREESITTER_SPECS

    spec = TREESITTER_SPECS.get(spec_name)
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
