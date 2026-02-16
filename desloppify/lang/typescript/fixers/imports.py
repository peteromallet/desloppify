"""Unused import fixer: removes unused symbols from import statements."""

from collections import defaultdict

from .common import apply_fixer, process_unused_import_lines


def fix_unused_imports(entries: list[dict], *, dry_run: bool = False) -> list[dict]:
    """Remove unused imports from source files.

    Args:
        entries: Output of detect_unused(), filtered to category=="imports".
        dry_run: If True, don't write files, just report what would change.

    Returns:
        List of {file, removed: [symbols], lines_removed: int} dicts.
    """
    # Filter to imports only and group by file
    import_entries = [e for e in entries if e["category"] == "imports"]

    def transform(lines, file_entries):
        unused_symbols = {e["name"] for e in file_entries}
        unused_by_line: dict[int, list[str]] = defaultdict(list)
        for e in file_entries:
            unused_by_line[e["line"]].append(e["name"])

        new_lines = process_unused_import_lines(lines, unused_symbols, unused_by_line)
        removed = [e["name"] for e in file_entries]
        return new_lines, removed

    return apply_fixer(import_entries, transform, dry_run=dry_run)
