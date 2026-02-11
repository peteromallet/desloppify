"""Complexity signal detection: configurable per-language complexity signals."""

import re
from pathlib import Path

from ..utils import PROJECT_ROOT


def detect_complexity(path: Path, signals, file_finder,
                      threshold: int = 15, min_loc: int = 50) -> tuple[list[dict], int]:
    """Detect files with complexity signals.

    Args:
        path: Directory to scan.
        signals: list of ComplexitySignal objects. Required.
        file_finder: callable(path) -> list[str]. Required.
        threshold: minimum score to flag a file.
        min_loc: minimum LOC to consider.

    Returns:
        (entries, total_files_checked)
    """
    files = file_finder(path)
    entries = []
    for filepath in files:
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
            content = p.read_text()
            lines = content.splitlines()
            loc = len(lines)
            if loc < min_loc:
                continue

            file_signals = []
            score = 0

            for sig in signals:
                if sig.compute:
                    result = sig.compute(content, lines)
                    if result:
                        count, label = result
                        file_signals.append(label)
                        excess = max(0, count - sig.threshold) if sig.threshold else count
                        score += excess * sig.weight
                elif sig.pattern:
                    count = len(re.findall(sig.pattern, content, re.MULTILINE))
                    if count > sig.threshold:
                        file_signals.append(f"{count} {sig.name}")
                        score += (count - sig.threshold) * sig.weight

            if file_signals and score >= threshold:
                entries.append({
                    "file": filepath, "loc": loc, "score": score,
                    "signals": file_signals,
                })
        except (OSError, UnicodeDecodeError):
            continue
    return sorted(entries, key=lambda e: -e["score"]), len(files)
