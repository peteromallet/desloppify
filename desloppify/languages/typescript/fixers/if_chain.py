"""Empty if-chain fixer: deletes if/else chains where all branches are empty."""

from typing import Any

from desloppify.languages._framework.base.types import FixResult
from desloppify.languages.typescript.detectors.smells.helpers import scan_code
from desloppify.languages.typescript.fixers.fixer_io import apply_fixer
from desloppify.languages.typescript.fixers.syntax_scan import collapse_blank_lines


def fix_empty_if_chain(
    entries: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> FixResult:
    """Delete if/else chains where all branches are empty."""

    def transform(
        lines: list[str],
        file_entries: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        lines_to_remove: set[int] = set()

        for e in file_entries:
            line_idx = e["line"] - 1
            if line_idx < 0 or line_idx >= len(lines):
                continue

            end = _find_if_chain_end(lines, line_idx)
            for idx in range(line_idx, end + 1):
                lines_to_remove.add(idx)

        new_lines = collapse_blank_lines(lines, lines_to_remove)
        return new_lines, ["empty_if_chain"]

    return FixResult(entries=apply_fixer(entries, transform, dry_run=dry_run))


def _find_if_chain_end(lines: list[str], start: int) -> int:
    """Find the last line of an if/else chain starting at `start`.

    Tracks brace depth. Chain ends when braces balance and no else follows.
    """
    brace_depth = 0
    found_brace = False

    for i in range(start, min(start + 100, len(lines))):
        line = lines[i]
        for ci, ch, in_s in scan_code(line):
            if in_s:
                continue
            if ch == "{":
                brace_depth += 1
                found_brace = True
            elif ch == "}":
                brace_depth -= 1
                if found_brace and brace_depth == 0:
                    rest = line[ci + 1 :].strip()
                    if rest.startswith("else"):
                        continue
                    j = i + 1
                    while j < len(lines) and lines[j].strip() == "":
                        j += 1
                    if j < len(lines) and lines[j].strip().startswith("else"):
                        continue
                    return i

    return start
