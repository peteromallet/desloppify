"""Remediation plan generation helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def empty_plan(state: dict[str, Any], lang_name: str) -> str:
    """Build the empty remediation plan output."""
    from desloppify.intelligence.review._prepare.remediation_engine import (
        empty_plan as _empty_plan,
    )

    return _empty_plan(state, lang_name)


def generate_remediation_plan(
    state: dict[str, Any],
    lang_name: str,
    *,
    output_path: Path | None = None,
) -> str:
    """Generate remediation markdown for open holistic findings."""
    from desloppify.intelligence.review._prepare.remediation_engine import (
        generate_remediation_plan as _generate_remediation_plan,
    )

    return _generate_remediation_plan(
        state,
        lang_name,
        output_path=output_path,
    )


__all__ = ["empty_plan", "generate_remediation_plan"]
