"""move command: move a file or directory and update all import references."""

import os
import re
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


def _detect_lang_from_dir(source_dir: str) -> str | None:
    """Detect language from files in a directory."""
    source_path = Path(source_dir)
    for f in source_path.rglob("*"):
        if f.is_file():
            lang = _detect_lang_from_ext(str(f))
            if lang:
                return lang
    return None


def _resolve_lang_for_move(source_abs: str, args) -> str | None:
    """Resolve language for a move operation, from extension or --lang flag."""
    lang_name = _detect_lang_from_ext(source_abs)
    if not lang_name:
        from ..cli import _resolve_lang
        lang = _resolve_lang(args)
        if lang:
            lang_name = lang.name
    return lang_name


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
    """Move a file or directory and update all import references."""
    source_rel = args.source
    source_abs = resolve_path(source_rel)
    source_path = Path(source_abs)

    if source_path.is_dir():
        return _cmd_move_dir(args, source_abs)

    if not source_path.is_file():
        print(c(f"Source not found: {rel(source_abs)}", "red"), file=sys.stderr)
        sys.exit(1)

    dest_abs = _resolve_dest(source_rel, args.dest)

    if Path(dest_abs).exists():
        print(c(f"Destination already exists: {rel(dest_abs)}", "red"), file=sys.stderr)
        sys.exit(1)

    dry_run = getattr(args, "dry_run", False)

    # Detect language from file extension, fall back to --lang
    lang_name = _resolve_lang_for_move(source_abs, args)
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


def _cmd_move_dir(args, source_abs: str):
    """Move a directory (package) and update all import references."""
    source_path = Path(source_abs)
    dest_abs = resolve_path(args.dest)
    dry_run = getattr(args, "dry_run", False)

    if Path(dest_abs).exists():
        print(c(f"Destination already exists: {rel(dest_abs)}", "red"), file=sys.stderr)
        sys.exit(1)

    # Detect language from directory contents or --lang
    lang_name = _detect_lang_from_dir(source_abs)
    if not lang_name:
        from ..cli import _resolve_lang
        lang = _resolve_lang(args)
        if lang:
            lang_name = lang.name
    if not lang_name:
        print(c("Cannot detect language from directory contents. Use --lang.", "red"),
              file=sys.stderr)
        sys.exit(1)

    from ..lang import get_lang
    lang = get_lang(lang_name)

    # Find all source files in the directory
    ext_map = {"python": [".py"], "typescript": [".ts", ".tsx"]}
    extensions = ext_map.get(lang_name, [])
    source_files = []
    for ext in extensions:
        source_files.extend(source_path.rglob(f"*{ext}"))
    source_files = sorted(str(f.resolve()) for f in source_files if f.is_file())

    if not source_files:
        print(c(f"No {lang_name} files found in {rel(source_abs)}", "yellow"), file=sys.stderr)
        sys.exit(1)

    # Build the dep graph once for all files
    scan_path = Path(resolve_path(lang.default_src))
    graph = lang.build_dep_graph(scan_path)

    # Compute the file mapping: source_file -> dest_file
    file_moves: list[tuple[str, str]] = []
    for src_file in source_files:
        rel_in_dir = Path(src_file).relative_to(source_path)
        dst_file = str(Path(dest_abs) / rel_in_dir)
        file_moves.append((src_file, dst_file))

    # Set of files being moved (to detect intra-package imports)
    moving_files = {src for src, _ in file_moves}

    # Compute all replacements for each file
    all_importer_changes: dict[str, list[tuple[str, str]]] = {}
    intra_pkg_changes: dict[str, list[tuple[str, str]]] = {}
    all_self_changes: dict[str, list[tuple[str, str]]] = {}

    for src_file, dst_file in file_moves:
        importer_changes, self_changes = _compute_replacements(
            lang_name, src_file, dst_file, graph)

        for filepath, replacements in importer_changes.items():
            if filepath in moving_files:
                # Intra-package importer — only keep ABSOLUTE import changes.
                # Relative imports between co-moving files don't need updating.
                abs_only = [(old, new) for old, new in replacements
                            if not re.match(r"from\s+\.", old)]
                if abs_only:
                    if filepath in intra_pkg_changes:
                        existing = set(intra_pkg_changes[filepath])
                        intra_pkg_changes[filepath].extend(r for r in abs_only if r not in existing)
                    else:
                        intra_pkg_changes[filepath] = list(abs_only)
            else:
                if filepath in all_importer_changes:
                    existing = set(all_importer_changes[filepath])
                    all_importer_changes[filepath].extend(r for r in replacements if r not in existing)
                else:
                    all_importer_changes[filepath] = list(replacements)

        if self_changes:
            # Filter self-changes: only keep imports pointing OUTSIDE the moved dir.
            # Intra-package relative imports stay the same because files move together.
            filtered_self = []
            if lang_name == "python":
                from ._move_py import _resolve_py_relative
                for old_str, new_str in self_changes:
                    src_dir = Path(src_file).parent
                    m = re.match(r"from\s+(\.+)(\w*(?:\.\w+)*)", old_str)
                    if m:
                        dots, remainder = m.group(1), m.group(2)
                        resolved = _resolve_py_relative(src_dir, dots, remainder)
                        if resolved and resolved in moving_files:
                            continue  # intra-package relative import, skip
                    filtered_self.append((old_str, new_str))
            else:
                filtered_self = self_changes

            if filtered_self:
                all_self_changes[src_file] = filtered_self

    # Report — use trailing sep to avoid matching e.g. source/db_operations for source/db
    source_prefix = source_abs + os.sep
    external_changes = {k: v for k, v in all_importer_changes.items()
                        if not k.startswith(source_prefix)}

    total_changes = len(external_changes) + len(intra_pkg_changes) + len(all_self_changes)
    total_replacements = (sum(len(r) for r in external_changes.values()) +
                          sum(len(r) for r in intra_pkg_changes.values()) +
                          sum(len(r) for r in all_self_changes.values()))

    print(c(f"\n  Move directory: {rel(source_abs)}/ → {rel(dest_abs)}/", "bold"))
    print(c(f"  {len(file_moves)} files in package", "dim"))
    print(c(f"  {total_replacements} import replacements across {total_changes} files\n", "dim"))

    if all_self_changes:
        print(c(f"  Own imports ({sum(len(v) for v in all_self_changes.values())} changes across "
                f"{len(all_self_changes)} files):", "cyan"))
        for src_file, changes in sorted(all_self_changes.items()):
            print(f"    {rel(src_file)}:")
            for old, new in changes:
                print(f"      {old}  →  {new}")
        print()

    if intra_pkg_changes:
        print(c(f"  Intra-package imports ({sum(len(v) for v in intra_pkg_changes.values())} changes "
                f"across {len(intra_pkg_changes)} files):", "cyan"))
        for filepath, replacements in sorted(intra_pkg_changes.items()):
            print(f"    {rel(filepath)}:")
            for old, new in replacements:
                print(f"      {old}  →  {new}")
        print()

    if external_changes:
        print(c(f"  External importers ({len(external_changes)} files):", "cyan"))
        for filepath, replacements in sorted(external_changes.items()):
            print(f"    {rel(filepath)}:")
            for old, new in replacements:
                print(f"      {old}  →  {new}")
        print()

    if not external_changes and not intra_pkg_changes and not all_self_changes:
        print(c("  No import references found — only the directory will be moved.", "dim"))
        print()

    if dry_run:
        print(c("  Dry run — no files modified.", "yellow"))
        return

    # Execute: move the entire directory at once
    Path(dest_abs).parent.mkdir(parents=True, exist_ok=True)
    shutil.move(source_abs, dest_abs)

    # Apply self-import and intra-package changes to the moved files (now at dest)
    all_internal_changes: dict[str, list[tuple[str, str]]] = {}
    for src_file, changes in all_self_changes.items():
        all_internal_changes.setdefault(src_file, []).extend(changes)
    for src_file, changes in intra_pkg_changes.items():
        all_internal_changes.setdefault(src_file, []).extend(changes)

    for src_file, changes in all_internal_changes.items():
        rel_in_dir = Path(src_file).relative_to(source_path)
        dest_file = Path(dest_abs) / rel_in_dir
        content = dest_file.read_text()
        for old_str, new_str in changes:
            content = content.replace(old_str, new_str)
        dest_file.write_text(content)

    # Apply importer changes to external files
    for filepath, replacements in external_changes.items():
        content = Path(filepath).read_text()
        for old_str, new_str in replacements:
            content = content.replace(old_str, new_str)
        Path(filepath).write_text(content)

    print(c("  Done.", "green"))
    if lang_name == "typescript":
        print(c("  Run `npx tsc --noEmit` to verify.", "dim"))
    print()
