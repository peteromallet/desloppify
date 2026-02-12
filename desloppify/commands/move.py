"""move command: move a file and update all import references."""

import shutil
import sys
from pathlib import Path

from ..utils import c, rel, resolve_path


def _dedup(replacements: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Deduplicate replacement tuples while preserving order."""
    seen: set[tuple[str, str]] = set()
    result = []
    for pair in replacements:
        if pair not in seen:
            seen.add(pair)
            result.append(pair)
    return result


# ── Language detection ────────────────────────────────────

_EXT_TO_LANG = {
    ".ts": "typescript",
    ".tsx": "typescript",
    ".py": "python",
}


def _detect_lang_from_ext(source: str) -> str | None:
    """Detect language from file extension."""
    ext = Path(source).suffix
    return _EXT_TO_LANG.get(ext)


# ── Path helpers ──────────────────────────────────────────


def _resolve_dest(source: str, dest_raw: str) -> str:
    """Resolve destination path, keeping source filename if dest is a directory."""
    dest_path = Path(dest_raw)
    # If it looks like a directory target (existing dir or ends with /)
    if dest_path.is_dir() or dest_raw.endswith("/"):
        dest_path = dest_path / Path(source).name
    return resolve_path(str(dest_path))


# ── Replacement dispatch ─────────────────────────────────


def _compute_replacements(
    lang_name: str, source_abs: str, dest_abs: str, graph: dict,
) -> tuple[dict[str, list[tuple[str, str]]], list[tuple[str, str]]]:
    """Dispatch to language-specific replacement finders.

    Returns (importer_changes, self_changes).
    """
    if lang_name == "typescript":
        from ._move_ts import find_ts_replacements, find_ts_self_replacements
        return (
            find_ts_replacements(source_abs, dest_abs, graph),
            find_ts_self_replacements(source_abs, dest_abs, graph),
        )
    elif lang_name == "python":
        from ._move_py import find_py_replacements, find_py_self_replacements
        return (
            find_py_replacements(source_abs, dest_abs, graph),
            find_py_self_replacements(source_abs, dest_abs, graph),
        )
    else:
        print(c(f"Move not yet supported for language: {lang_name}", "red"), file=sys.stderr)
        sys.exit(1)


# ── Reporting ─────────────────────────────────────────────


def _print_plan(
    source_abs: str, dest_abs: str,
    importer_changes: dict[str, list[tuple[str, str]]],
    self_changes: list[tuple[str, str]],
) -> None:
    """Print the move plan: summary, self-imports, and importer changes."""
    total_files = len(importer_changes) + (1 if self_changes else 0)
    total_replacements = sum(len(r) for r in importer_changes.values()) + len(self_changes)

    print(c(f"\n  Move: {rel(source_abs)} → {rel(dest_abs)}", "bold"))
    print(c(f"  {total_replacements} import replacements across {total_files} files\n", "dim"))

    if self_changes:
        print(c(f"  Own imports ({len(self_changes)} changes):", "cyan"))
        for old, new in self_changes:
            print(f"    {old}  →  {new}")
        print()

    if importer_changes:
        print(c(f"  Importers ({len(importer_changes)} files):", "cyan"))
        for filepath, replacements in sorted(importer_changes.items()):
            print(f"    {rel(filepath)}:")
            for old, new in replacements:
                print(f"      {old}  →  {new}")
        print()

    if not importer_changes and not self_changes:
        print(c("  No import references found — only the file will be moved.", "dim"))
        print()


# ── Apply changes ─────────────────────────────────────────


def _apply_changes(
    source_abs: str, dest_abs: str,
    importer_changes: dict[str, list[tuple[str, str]]],
    self_changes: list[tuple[str, str]],
) -> None:
    """Move the file and apply all import replacements."""
    Path(dest_abs).parent.mkdir(parents=True, exist_ok=True)
    shutil.move(source_abs, dest_abs)

    # Apply self-import changes to the moved file (now at dest)
    if self_changes:
        content = Path(dest_abs).read_text()
        for old_str, new_str in self_changes:
            content = content.replace(old_str, new_str)
        Path(dest_abs).write_text(content)

    # Apply importer changes
    for filepath, replacements in importer_changes.items():
        content = Path(filepath).read_text()
        for old_str, new_str in replacements:
            content = content.replace(old_str, new_str)
        Path(filepath).write_text(content)


# ── Main command ──────────────────────────────────────────


def cmd_move(args):
    """Move a file and update all import references."""
    source_rel = args.source
    source_abs = resolve_path(source_rel)

    if not Path(source_abs).is_file():
        print(c(f"Source not found: {rel(source_abs)}", "red"), file=sys.stderr)
        sys.exit(1)

    dest_abs = _resolve_dest(source_rel, args.dest)

    if Path(dest_abs).exists():
        print(c(f"Destination already exists: {rel(dest_abs)}", "red"), file=sys.stderr)
        sys.exit(1)

    dry_run = getattr(args, "dry_run", False)

    # Detect language from file extension, fall back to --lang
    lang_name = _detect_lang_from_ext(source_abs)
    if not lang_name:
        from ..cli import _resolve_lang
        lang = _resolve_lang(args)
        if lang:
            lang_name = lang.name
    if not lang_name:
        print(c("Cannot detect language. Use --lang or ensure file has .ts/.tsx/.py extension.", "red"),
              file=sys.stderr)
        sys.exit(1)

    from ..lang import get_lang
    lang = get_lang(lang_name)

    # Use the language-specific default path for scanning.
    # args.path may have been pre-resolved for a different language (e.g. src/ for TS
    # when moving a Python file), so always use the auto-detected lang's default.
    scan_path = Path(resolve_path(lang.default_src))
    graph = lang.build_dep_graph(scan_path)

    # Compute replacements based on language
    importer_changes, self_changes = _compute_replacements(
        lang_name, source_abs, dest_abs, graph,
    )

    # Report
    _print_plan(source_abs, dest_abs, importer_changes, self_changes)

    if dry_run:
        print(c("  Dry run — no files modified.", "yellow"))
        return

    # Execute
    _apply_changes(source_abs, dest_abs, importer_changes, self_changes)

    print(c("  Done.", "green"))
    if lang_name == "typescript":
        print(c("  Run `npx tsc --noEmit` to verify.", "dim"))
    print()
