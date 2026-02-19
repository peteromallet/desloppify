"""Structural signal helpers shared across language phase implementations."""

from __future__ import annotations

from pathlib import Path

from desloppify.engine.state_internal.schema import Finding
from desloppify.state import make_finding
from desloppify.utils import PROJECT_ROOT, resolve_path


def add_structural_signal(structural: dict, file: str, signal: str, detail: dict):
    """Add a complexity signal to the per-file structural dict.

    Accumulates signals per file so they can be merged into tiered findings.
    """
    f = resolve_path(file)
    structural.setdefault(f, {"signals": [], "detail": {}})
    structural[f]["signals"].append(signal)
    structural[f]["detail"].update(detail)


def merge_structural_signals(
    structural: dict,
    stderr_fn,
    *,
    complexity_only_min: int = 35,
) -> list[Finding]:
    """Convert per-file structural signals into tiered findings.

    3+ signals -> T4/high (needs decomposition).
    1-2 signals -> T3/medium.
    Complexity-only files (no large/god signals) need score >= complexity_only_min
    to be flagged — lower complexity in small files is normal, not decomposition-worthy.
    """
    results = []
    suppressed = 0
    for filepath, data in structural.items():
        if "loc" not in data["detail"]:
            try:
                p = (
                    Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
                )
                data["detail"]["loc"] = len(p.read_text().splitlines())
            except (OSError, UnicodeDecodeError):
                data["detail"]["loc"] = 0

        # Suppress complexity-only findings below the elevated threshold.
        signals = data["signals"]
        is_complexity_only = all(s.startswith("complexity") for s in signals)
        if is_complexity_only:
            score = data["detail"].get("complexity_score", 0)
            if score < complexity_only_min:
                suppressed += 1
                continue

        signal_count = len(signals)
        tier = 4 if signal_count >= 3 else 3
        confidence = "high" if signal_count >= 3 else "medium"
        summary = "Needs decomposition: " + " / ".join(signals)
        results.append(
            make_finding(
                "structural",
                filepath,
                "",
                tier=tier,
                confidence=confidence,
                summary=summary,
                detail=data["detail"],
            )
        )
    if suppressed:
        stderr_fn(
            "         "
            f"{suppressed} complexity-only files below threshold (< {complexity_only_min})"
        )
    stderr_fn(f"         -> {len(results)} structural findings")
    return results


__all__ = ["add_structural_signal", "merge_structural_signals"]
