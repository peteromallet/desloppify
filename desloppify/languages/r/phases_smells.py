"""R smells phase runner."""

from __future__ import annotations

from pathlib import Path

from desloppify.base.output.terminal import log
from desloppify.languages._framework.base.smell_contracts import normalize_smell_entries
from desloppify.languages._framework.base.types import LangRuntimeContract
from desloppify.languages._framework.issue_factories import make_smell_issues
from desloppify.languages.r.detectors.smells import detect_smells


def phase_smells(path: Path, lang: LangRuntimeContract) -> tuple[list, dict[str, int]]:
    """Run R-specific smell detectors and normalize them into issues."""
    smell_entries, total_smell_files = detect_smells(path)
    normalized_smells = normalize_smell_entries(smell_entries)
    results = make_smell_issues(
        [entry.to_mapping() for entry in normalized_smells],
        log,
    )
    return results, {"smells": total_smell_files}


__all__ = ["phase_smells"]
