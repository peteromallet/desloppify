"""move command: move a file or directory and update all import references."""

import importlib
import os
import shutil
import sys
from pathlib import Path

from ..utils import colorize, rel, resolve_path


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


def _build_ext_to_lang_map() -> dict[str, str]:
    """Build extension→language map from registered language configs."""
    from ..lang import available_langs, get_lang

    ext_map: dict[str, str] = {}
    for lang_name in available_langs():
        cfg = get_lang(lang_name)
        for ext in cfg.extensions:
            ext_map.setdefault(ext, lang_name)
    return ext_map


_EXT_TO_LANG = _build_ext_to_lang_map()


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
    """Resolve language for a move operation.

    Explicit ``--lang`` takes priority. Otherwise, infer from file extension and
    finally fall back to auto-detection.
    """
    explicit_lang = getattr(args, "lang", None)
    if explicit_lang:
        from ._helpers import resolve_lang
        lang = resolve_lang(args)
        if lang:
            return lang.name

    lang_name = _detect_lang_from_ext(source_abs)
    if not lang_name:
        from ._helpers import resolve_lang
        lang = resolve_lang(args)
        if lang:
            lang_name = lang.name
    return lang_name


def _supported_ext_hint() -> str:
    exts = ", ".join(sorted(_EXT_TO_LANG))
    return exts or "<none>"


def _load_lang_move_module(lang_name: str):
    """Load language-specific move helpers from lang/<name>/move.py."""
    try:
        return importlib.import_module(f"..lang.{lang_name}.move", package="desloppify.commands")
    except ImportError as ex:
        print(colorize(f"Move not yet supported for language: {lang_name} ({ex})", "red"), file=sys.stderr)
        sys.exit(1)


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
    move_mod, source_abs: str, dest_abs: str, graph: dict,
) -> tuple[dict[str, list[tuple[str, str]]], list[tuple[str, str]]]:
    """Compute importer/self replacements via language move module."""
    return (
        move_mod.find_replacements(source_abs, dest_abs, graph),
        move_mod.find_self_replacements(source_abs, dest_abs, graph),
    )


# ── Reporting ─────────────────────────────────────────────


def _print_plan(
    source_abs: str, dest_abs: str,
    importer_changes: dict[str, list[tuple[str, str]]],
    self_changes: list[tuple[str, str]],
) -> None:
    """Print the move plan: summary, self-imports, and importer changes."""
    total_files = len(importer_changes) + (1 if self_changes else 0)
    total_replacements = sum(len(r) for r in importer_changes.values()) + len(self_changes)

    print(colorize(f"\n  Move: {rel(source_abs)} → {rel(dest_abs)}", "bold"))
    print(colorize(f"  {total_replacements} import replacements across {total_files} files\n", "dim"))

    if self_changes:
        print(colorize(f"  Own imports ({len(self_changes)} changes):", "cyan"))
        for old, new in self_changes:
            print(f"    {old}  →  {new}")
        print()

    if importer_changes:
        print(colorize(f"  Importers ({len(importer_changes)} files):", "cyan"))
        for filepath, replacements in sorted(importer_changes.items()):
            print(f"    {rel(filepath)}:")
            for old, new in replacements:
                print(f"      {old}  →  {new}")
        print()

    if not importer_changes and not self_changes:
        print(colorize("  No import references found — only the file will be moved.", "dim"))
        print()


# ── Apply changes ─────────────────────────────────────────


def _safe_write(filepath: str | Path, content: str) -> None:
    """Atomic write: write to temp file then rename."""
    p = Path(filepath)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(content)
        os.replace(str(tmp), str(p))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _apply_changes(
    source_abs: str, dest_abs: str,
    importer_changes: dict[str, list[tuple[str, str]]],
    self_changes: list[tuple[str, str]],
) -> None:
    """Move the file and apply all import replacements.

    Uses a two-phase approach: compute all new content first, then write.
    On error, attempts to roll back by restoring original file contents.
    """
    # Phase 1: Read all files and compute new contents (no writes yet)
    new_contents: dict[str, str] = {}
    if self_changes:
        content = Path(source_abs).read_text()
        for old_str, new_str in self_changes:
            content = content.replace(old_str, new_str)
        new_contents[dest_abs] = content

    for filepath, replacements in importer_changes.items():
        content = Path(filepath).read_text()
        for old_str, new_str in replacements:
            content = content.replace(old_str, new_str)
        new_contents[filepath] = content

    # Phase 2: Move file and write all changes
    Path(dest_abs).parent.mkdir(parents=True, exist_ok=True)
    written_files: dict[str, str] = {}  # filepath -> original content (for rollback)
    try:
        shutil.move(source_abs, dest_abs)

        # Write self-import changes to moved file
        if dest_abs in new_contents:
            written_files[dest_abs] = Path(dest_abs).read_text()
            _safe_write(dest_abs, new_contents[dest_abs])

        # Write importer changes
        for filepath in importer_changes:
            if filepath in new_contents:
                written_files[filepath] = Path(filepath).read_text()
                _safe_write(filepath, new_contents[filepath])

    except Exception as ex:
        print(colorize(f"\n  Error during move: {ex}", "red"), file=sys.stderr)
        print(colorize("  Rolling back...", "yellow"), file=sys.stderr)
        # Restore any files we already wrote
        for fp, original in written_files.items():
            try:
                _safe_write(fp, original)
            except OSError:
                print(colorize(f"  WARNING: Could not restore {rel(fp)}", "red"), file=sys.stderr)
        # Move the file back if it was moved
        if Path(dest_abs).exists() and not Path(source_abs).exists():
            try:
                shutil.move(dest_abs, source_abs)
            except OSError:
                print(colorize(f"  WARNING: Could not move file back to {rel(source_abs)}", "red"),
                      file=sys.stderr)
        raise


# ── Main command ──────────────────────────────────────────


def cmd_move(args) -> None:
    """Move a file or directory and update all import references."""
    source_rel = args.source
    source_abs = resolve_path(source_rel)
    source_path = Path(source_abs)

    if source_path.is_dir():
        return _cmd_move_dir(args, source_abs)

    if not source_path.is_file():
        print(colorize(f"Source not found: {rel(source_abs)}", "red"), file=sys.stderr)
        sys.exit(1)

    dest_abs = _resolve_dest(source_rel, args.dest)

    if Path(dest_abs).exists():
        print(colorize(f"Destination already exists: {rel(dest_abs)}", "red"), file=sys.stderr)
        sys.exit(1)

    dry_run = getattr(args, "dry_run", False)

    # Detect language from file extension, fall back to --lang
    lang_name = _resolve_lang_for_move(source_abs, args)
    if not lang_name:
        print(colorize(
            f"Cannot detect language. Use --lang or ensure file has one of: {_supported_ext_hint()}",
            "red"),
              file=sys.stderr)
        sys.exit(1)

    from ..lang import get_lang
    lang = get_lang(lang_name)
    move_mod = _load_lang_move_module(lang_name)

    # Use the language-specific default path for scanning.
    # args.path may have been pre-resolved for a different language (e.g. src/ for TS
    # when moving a Python file), so always use the auto-detected lang's default.
    scan_path = Path(resolve_path(lang.default_src))
    graph = lang.build_dep_graph(scan_path)

    # Compute replacements based on language
    importer_changes, self_changes = _compute_replacements(
        move_mod, source_abs, dest_abs, graph,
    )

    # Report
    _print_plan(source_abs, dest_abs, importer_changes, self_changes)

    if dry_run:
        print(colorize("  Dry run — no files modified.", "yellow"))
        return

    # Execute
    _apply_changes(source_abs, dest_abs, importer_changes, self_changes)

    print(colorize("  Done.", "green"))
    verify_hint = getattr(move_mod, "VERIFY_HINT", "")
    if verify_hint:
        print(colorize(f"  Run `{verify_hint}` to verify.", "dim"))
    print()


def _cmd_move_dir(args, source_abs: str):
    """Move a directory (package) and update all import references."""
    source_path = Path(source_abs)
    dest_abs = resolve_path(args.dest)
    dry_run = getattr(args, "dry_run", False)

    if Path(dest_abs).exists():
        print(colorize(f"Destination already exists: {rel(dest_abs)}", "red"), file=sys.stderr)
        sys.exit(1)

    # Detect language from explicit --lang first; otherwise infer from contents.
    lang_name = None
    if getattr(args, "lang", None):
        from ._helpers import resolve_lang
        lang = resolve_lang(args)
        if lang:
            lang_name = lang.name
    else:
        lang_name = _detect_lang_from_dir(source_abs)

    if not lang_name:
        from ._helpers import resolve_lang
        lang = resolve_lang(args)
        if lang:
            lang_name = lang.name
    if not lang_name:
        print(colorize(
            f"Cannot detect language from directory contents. Use --lang "
            f"(supported extensions: {_supported_ext_hint()}).",
            "red"),
              file=sys.stderr)
        sys.exit(1)

    from ..lang import get_lang
    lang = get_lang(lang_name)
    move_mod = _load_lang_move_module(lang_name)

    # Find all source files in the directory
    extensions = list(lang.extensions)
    source_files = []
    for ext in extensions:
        source_files.extend(source_path.rglob(f"*{ext}"))
    source_files = sorted(str(f.resolve()) for f in source_files if f.is_file())

    if not source_files:
        print(colorize(f"No {lang_name} files found in {rel(source_abs)}", "yellow"), file=sys.stderr)
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
    intra_filter = getattr(
        move_mod,
        "filter_intra_package_importer_changes",
        lambda _source, replacements, _moving: replacements,
    )
    self_filter = getattr(
        move_mod,
        "filter_directory_self_changes",
        lambda _source, replacements, _moving: replacements,
    )

    for src_file, dst_file in file_moves:
        importer_changes, self_changes = _compute_replacements(
            move_mod, src_file, dst_file, graph)

        for filepath, replacements in importer_changes.items():
            if filepath in moving_files:
                intra_changes = intra_filter(
                    src_file, replacements, moving_files)
                if intra_changes:
                    if filepath in intra_pkg_changes:
                        existing = set(intra_pkg_changes[filepath])
                        intra_pkg_changes[filepath].extend(
                            r for r in intra_changes if r not in existing)
                    else:
                        intra_pkg_changes[filepath] = list(intra_changes)
            else:
                if filepath in all_importer_changes:
                    existing = set(all_importer_changes[filepath])
                    all_importer_changes[filepath].extend(r for r in replacements if r not in existing)
                else:
                    all_importer_changes[filepath] = list(replacements)

        if self_changes:
            filtered_self = self_filter(
                src_file, self_changes, moving_files)
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

    print(colorize(f"\n  Move directory: {rel(source_abs)}/ → {rel(dest_abs)}/", "bold"))
    print(colorize(f"  {len(file_moves)} files in package", "dim"))
    print(colorize(f"  {total_replacements} import replacements across {total_changes} files\n", "dim"))

    if all_self_changes:
        print(colorize(f"  Own imports ({sum(len(v) for v in all_self_changes.values())} changes across "
                f"{len(all_self_changes)} files):", "cyan"))
        for src_file, changes in sorted(all_self_changes.items()):
            print(f"    {rel(src_file)}:")
            for old, new in changes:
                print(f"      {old}  →  {new}")
        print()

    if intra_pkg_changes:
        print(colorize(f"  Intra-package imports ({sum(len(v) for v in intra_pkg_changes.values())} changes "
                f"across {len(intra_pkg_changes)} files):", "cyan"))
        for filepath, replacements in sorted(intra_pkg_changes.items()):
            print(f"    {rel(filepath)}:")
            for old, new in replacements:
                print(f"      {old}  →  {new}")
        print()

    if external_changes:
        print(colorize(f"  External importers ({len(external_changes)} files):", "cyan"))
        for filepath, replacements in sorted(external_changes.items()):
            print(f"    {rel(filepath)}:")
            for old, new in replacements:
                print(f"      {old}  →  {new}")
        print()

    if not external_changes and not intra_pkg_changes and not all_self_changes:
        print(colorize("  No import references found — only the directory will be moved.", "dim"))
        print()

    if dry_run:
        print(colorize("  Dry run — no files modified.", "yellow"))
        return

    # Phase 1: Compute all new contents (no writes yet)
    all_internal_changes: dict[str, list[tuple[str, str]]] = {}
    for src_file, changes in all_self_changes.items():
        all_internal_changes.setdefault(src_file, []).extend(changes)
    for src_file, changes in intra_pkg_changes.items():
        all_internal_changes.setdefault(src_file, []).extend(changes)

    # Phase 2: Execute with rollback on failure
    Path(dest_abs).parent.mkdir(parents=True, exist_ok=True)
    written_files: dict[str, str] = {}  # filepath -> original content
    try:
        shutil.move(source_abs, dest_abs)

        for src_file, changes in all_internal_changes.items():
            rel_in_dir = Path(src_file).relative_to(source_path)
            dest_file = Path(dest_abs) / rel_in_dir
            original = dest_file.read_text()
            content = original
            for old_str, new_str in changes:
                content = content.replace(old_str, new_str)
            written_files[str(dest_file)] = original
            _safe_write(dest_file, content)

        for filepath, replacements in external_changes.items():
            original = Path(filepath).read_text()
            content = original
            for old_str, new_str in replacements:
                content = content.replace(old_str, new_str)
            written_files[filepath] = original
            _safe_write(filepath, content)

    except Exception as ex:
        print(colorize(f"\n  Error during directory move: {ex}", "red"), file=sys.stderr)
        print(colorize("  Rolling back...", "yellow"), file=sys.stderr)
        for fp, original in written_files.items():
            try:
                _safe_write(fp, original)
            except OSError:
                print(colorize(f"  WARNING: Could not restore {rel(fp)}", "red"), file=sys.stderr)
        if Path(dest_abs).exists() and not Path(source_abs).exists():
            try:
                shutil.move(dest_abs, source_abs)
            except OSError:
                print(colorize(f"  WARNING: Could not move directory back to {rel(source_abs)}", "red"),
                      file=sys.stderr)
        raise

    print(colorize("  Done.", "green"))
    verify_hint = getattr(move_mod, "VERIFY_HINT", "")
    if verify_hint:
        print(colorize(f"  Run `{verify_hint}` to verify.", "dim"))
    print()
