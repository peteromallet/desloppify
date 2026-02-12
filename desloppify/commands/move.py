"""move command: move a file and update all import references."""

import os
import re
import shutil
import sys
from pathlib import Path

from ..utils import PROJECT_ROOT, SRC_PATH, c, rel, resolve_path


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


# ── Helpers ───────────────────────────────────────────────


def _dedup(replacements: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Deduplicate replacement tuples while preserving order."""
    seen: set[tuple[str, str]] = set()
    result = []
    for pair in replacements:
        if pair not in seen:
            seen.add(pair)
            result.append(pair)
    return result


def _has_exact_module(line: str, module: str) -> bool:
    """Check if a Python import line references this exact module (not a child).

    Uses lookaround instead of \\b because \\b treats '.' as a word boundary,
    causing 'source.foo' to falsely match inside 'source.foo.bar'.
    """
    return bool(re.search(rf'(?<!\w){re.escape(module)}(?![\w.])', line))


def _replace_exact_module(line: str, old_module: str, new_module: str) -> str:
    """Replace an exact module reference in a Python import line."""
    return re.sub(rf'(?<!\w){re.escape(old_module)}(?![\w.])', new_module, line)


# ── TypeScript import specifier computation ───────────────


def _compute_ts_specifiers(from_file: str, to_file: str) -> tuple[str | None, str]:
    """Compute both @/ alias and relative import specifiers for a TS file.

    Returns (alias_specifier_or_None, relative_specifier).
    alias_specifier is None if the target is outside src/.
    """
    to_path = Path(to_file)

    # @/ alias: only works for files under SRC_PATH
    alias = None
    try:
        to_rel_src = to_path.relative_to(SRC_PATH)
        alias = "@/" + _strip_ts_ext(str(to_rel_src))
        if alias.endswith("/index"):
            alias = alias[:-6]
    except ValueError:
        pass  # target outside src/

    # Relative specifier
    from_dir = Path(from_file).parent
    relative = os.path.relpath(to_file, from_dir)
    relative = _strip_ts_ext(relative)
    if not relative.startswith("."):
        relative = "./" + relative
    if relative.endswith("/index"):
        relative = relative[:-6]

    return alias, relative


def _strip_ts_ext(path: str) -> str:
    """Strip .ts/.tsx/.js/.jsx extension from an import path."""
    for ext in (".tsx", ".ts", ".jsx", ".js"):
        if path.endswith(ext):
            return path[:-len(ext)]
    return path


# ── Python import specifier computation ───────────────────


def _path_to_py_module(filepath: str, root: Path) -> str | None:
    """Convert a Python file path to a dotted module name relative to root.

    E.g. scripts/foo/commands/move.py -> scripts.foo.commands.move
    """
    try:
        rel_path = Path(filepath).relative_to(root)
    except ValueError:
        return None
    parts = list(rel_path.parts)
    # Strip .py extension from last part
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    # Strip __init__ (package itself)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


# ── Finding import lines and computing replacements ───────


def _find_ts_replacements(
    source_abs: str, dest_abs: str, graph: dict,
) -> dict[str, list[tuple[str, str]]]:
    """Compute all import string replacements needed for a TS file move.

    Returns {filepath: [(old_str, new_str), ...]}
    """
    changes: dict[str, list[tuple[str, str]]] = {}
    entry = graph.get(source_abs)
    if not entry:
        return changes

    importers = entry.get("importers", set())

    for importer in importers:
        if importer == source_abs:
            continue  # skip self-imports, handled separately

        # Compute old specifiers (what the importer currently uses)
        old_alias, old_relative = _compute_ts_specifiers(importer, source_abs)
        # Compute new specifiers
        new_alias, new_relative = _compute_ts_specifiers(importer, dest_abs)

        replacements = []

        try:
            content = Path(importer).read_text()
        except (OSError, UnicodeDecodeError):
            continue

        # Check which form the importer actually uses
        for old_spec, new_spec in [(old_alias, new_alias), (old_relative, new_relative)]:
            if old_spec is None or new_spec is None:
                continue
            if old_spec == new_spec:
                continue
            # Look for the old specifier in quotes
            for quote in ("'", '"'):
                target = f"{quote}{old_spec}{quote}"
                if target in content:
                    replacement = f"{quote}{new_spec}{quote}"
                    replacements.append((target, replacement))

        if replacements:
            changes[importer] = _dedup(replacements)

    return changes


def _find_ts_self_replacements(
    source_abs: str, dest_abs: str, graph: dict,
) -> list[tuple[str, str]]:
    """Compute replacements for the moved file's own relative imports.

    Only relative imports need updating — @/ imports are location-independent.
    """
    replacements = []
    entry = graph.get(source_abs)
    if not entry:
        return replacements

    try:
        content = Path(source_abs).read_text()
    except (OSError, UnicodeDecodeError):
        return replacements

    for imported_file in entry.get("imports", set()):
        # Compute old relative specifier (from source location)
        _, old_relative = _compute_ts_specifiers(source_abs, imported_file)
        # Compute new relative specifier (from dest location)
        _, new_relative = _compute_ts_specifiers(dest_abs, imported_file)

        if old_relative == new_relative:
            continue

        for quote in ("'", '"'):
            target = f"{quote}{old_relative}{quote}"
            if target in content:
                replacement = f"{quote}{new_relative}{quote}"
                replacements.append((target, replacement))

    return _dedup(replacements)


def _find_py_replacements(
    source_abs: str, dest_abs: str, graph: dict,
) -> dict[str, list[tuple[str, str]]]:
    """Compute all import string replacements needed for a Python file move.

    Returns {filepath: [(old_str, new_str), ...]}
    """
    changes: dict[str, list[tuple[str, str]]] = {}
    entry = graph.get(source_abs)
    if not entry:
        return changes

    # Compute old and new dotted module names
    old_module = _path_to_py_module(source_abs, PROJECT_ROOT)
    new_module = _path_to_py_module(dest_abs, PROJECT_ROOT)
    if not old_module or not new_module:
        return changes

    importers = entry.get("importers", set())

    for importer in importers:
        if importer == source_abs:
            continue

        try:
            content = Path(importer).read_text()
        except (OSError, UnicodeDecodeError):
            continue

        replacements = []
        importer_dir = Path(importer).parent

        for line in content.splitlines():
            stripped = line.strip()
            if not (stripped.startswith("from ") or stripped.startswith("import ")):
                continue

            # Handle absolute imports: from old.module import X / import old.module
            # Use word-boundary check to avoid matching old.module.child
            if _has_exact_module(stripped, old_module):
                new_line = _replace_exact_module(stripped, old_module, new_module)
                if new_line != stripped:
                    replacements.append((stripped, new_line))
                    continue

            # Handle relative imports
            m = re.match(r"from\s+(\.+)(\w*(?:\.\w+)*)\s+import", stripped)
            if m:
                dots = m.group(1)
                remainder = m.group(2)
                resolved = _resolve_py_relative(importer_dir, dots, remainder)
                if resolved and str(Path(resolved).resolve()) == source_abs:
                    # Recompute relative import from importer to new location
                    new_rel = _compute_py_relative_import(importer, dest_abs)
                    if new_rel:
                        old_from = f"from {dots}{remainder}"
                        new_from = f"from {new_rel}"
                        replacements.append((old_from, new_from))

        if replacements:
            changes[importer] = _dedup(replacements)

    return changes


def _find_py_self_replacements(
    source_abs: str, dest_abs: str, graph: dict,
) -> list[tuple[str, str]]:
    """Compute replacements for the moved file's own relative imports."""
    replacements = []
    entry = graph.get(source_abs)
    if not entry:
        return replacements

    try:
        content = Path(source_abs).read_text()
    except (OSError, UnicodeDecodeError):
        return replacements

    source_dir = Path(source_abs).parent

    for line in content.splitlines():
        stripped = line.strip()
        m = re.match(r"from\s+(\.+)(\w*(?:\.\w+)*)\s+import", stripped)
        if not m:
            continue

        dots = m.group(1)
        remainder = m.group(2)

        # Resolve what this relative import points to from the source location
        resolved = _resolve_py_relative(source_dir, dots, remainder)
        if not resolved:
            continue

        # Compute new relative import from dest location to the same target
        new_rel = _compute_py_relative_import(dest_abs, resolved)
        if not new_rel:
            continue

        old_from = f"from {dots}{remainder}"
        new_from = f"from {new_rel}"
        if old_from != new_from:
            replacements.append((old_from, new_from))

    return _dedup(replacements)


def _resolve_py_relative(source_dir: Path, dots: str, remainder: str) -> str | None:
    """Resolve a relative Python import to an absolute file path."""
    dot_count = len(dots)
    base = source_dir
    for _ in range(dot_count - 1):
        base = base.parent

    if remainder:
        parts = remainder.split(".")
        target_base = base
        for part in parts:
            target_base = target_base / part
    else:
        target_base = base

    # Try foo.py, foo/__init__.py
    candidate = Path(str(target_base) + ".py")
    if candidate.is_file():
        return str(candidate.resolve())
    candidate = target_base / "__init__.py"
    if candidate.is_file():
        return str(candidate.resolve())
    return None


def _compute_py_relative_import(from_file: str, to_file: str) -> str | None:
    """Compute a relative Python import string from from_file to to_file.

    Returns the 'from' part, e.g. '.foo' or '..bar.baz'.
    """
    from_dir = Path(from_file).parent

    # Find common ancestor
    try:
        rel_path = os.path.relpath(to_file, from_dir)
    except ValueError:
        return None

    parts = Path(rel_path).parts
    # Count leading '..' to determine dot count
    ups = 0
    for p in parts:
        if p == "..":
            ups += 1
        else:
            break

    # dots = ups + 1 (one dot = same package)
    dot_count = ups + 1
    remainder_parts = list(parts[ups:])

    # Strip .py extension from last part
    if remainder_parts and remainder_parts[-1].endswith(".py"):
        remainder_parts[-1] = remainder_parts[-1][:-3]
    # Strip __init__ (importing from package)
    if remainder_parts and remainder_parts[-1] == "__init__":
        remainder_parts = remainder_parts[:-1]

    dots = "." * dot_count
    remainder = ".".join(remainder_parts)
    return f"{dots}{remainder}"


# ── Main command ──────────────────────────────────────────


def _resolve_lang_for_move(source_abs: str, args):
    """Resolve language for a move operation, from extension or --lang flag."""
    lang_name = _detect_lang_from_ext(source_abs)
    if not lang_name:
        from ..cli import _resolve_lang
        lang = _resolve_lang(args)
        if lang:
            lang_name = lang.name
    return lang_name


def _detect_lang_from_dir(source_dir: str) -> str | None:
    """Detect language from files in a directory."""
    source_path = Path(source_dir)
    for f in source_path.rglob("*"):
        if f.is_file():
            lang = _detect_lang_from_ext(str(f))
            if lang:
                return lang
    return None


def _move_single_file(source_abs: str, dest_abs: str, lang_name: str, graph: dict,
                      dry_run: bool) -> tuple[dict, list]:
    """Compute and optionally apply replacements for a single file move.

    Returns (importer_changes, self_changes).
    """
    if lang_name == "typescript":
        importer_changes = _find_ts_replacements(source_abs, dest_abs, graph)
        self_changes = _find_ts_self_replacements(source_abs, dest_abs, graph)
    elif lang_name == "python":
        importer_changes = _find_py_replacements(source_abs, dest_abs, graph)
        self_changes = _find_py_self_replacements(source_abs, dest_abs, graph)
    else:
        return {}, []

    return importer_changes, self_changes


def _report_changes(source_label: str, dest_label: str, importer_changes: dict,
                    self_changes: list):
    """Print a summary of move changes."""
    total_files = len(importer_changes) + (1 if self_changes else 0)
    total_replacements = sum(len(r) for r in importer_changes.values()) + len(self_changes)

    print(c(f"\n  Move: {source_label} → {dest_label}", "bold"))
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


def _apply_changes(source_abs: str, dest_abs: str, importer_changes: dict,
                   self_changes: list):
    """Apply file move and import replacements."""
    Path(dest_abs).parent.mkdir(parents=True, exist_ok=True)
    shutil.move(source_abs, dest_abs)

    if self_changes:
        content = Path(dest_abs).read_text()
        for old_str, new_str in self_changes:
            content = content.replace(old_str, new_str)
        Path(dest_abs).write_text(content)

    for filepath, replacements in importer_changes.items():
        content = Path(filepath).read_text()
        for old_str, new_str in replacements:
            content = content.replace(old_str, new_str)
        Path(filepath).write_text(content)


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

    lang_name = _resolve_lang_for_move(source_abs, args)
    if not lang_name:
        print(c("Cannot detect language. Use --lang or ensure file has .ts/.tsx/.py extension.", "red"),
              file=sys.stderr)
        sys.exit(1)

    from ..lang import get_lang
    lang = get_lang(lang_name)

    scan_path = Path(resolve_path(lang.default_src))
    graph = lang.build_dep_graph(scan_path)

    importer_changes, self_changes = _move_single_file(
        source_abs, dest_abs, lang_name, graph, dry_run)

    _report_changes(rel(source_abs), rel(dest_abs), importer_changes, self_changes)

    if dry_run:
        print(c("  Dry run — no files modified.", "yellow"))
        return

    _apply_changes(source_abs, dest_abs, importer_changes, self_changes)

    print(c("  Done.", "green"))
    if lang_name == "typescript":
        print(c("  Run `npx tsc --noEmit` to verify.", "dim"))
    print()


def _cmd_move_dir(args, source_abs: str):
    """Move a directory (package) and update all import references."""
    source_path = Path(source_abs)
    dest_raw = args.dest
    dest_abs = resolve_path(dest_raw)
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

    # Determine file extensions for the language
    ext_map = {"python": [".py"], "typescript": [".ts", ".tsx"]}
    extensions = ext_map.get(lang_name, [])

    # Find all source files in the directory
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
        # Compute relative path within the source directory
        rel_in_dir = Path(src_file).relative_to(source_path)
        dst_file = str(Path(dest_abs) / rel_in_dir)
        file_moves.append((src_file, dst_file))

    # Set of files being moved (to detect intra-package imports)
    moving_files = {src for src, _ in file_moves}

    # Compute all replacements for each file
    # External: files outside the moved dir that import from it
    all_importer_changes: dict[str, list[tuple[str, str]]] = {}
    # Intra-package: files inside the moved dir that use absolute imports to siblings
    intra_pkg_changes: dict[str, list[tuple[str, str]]] = {}
    # Self: the moved file's own relative imports pointing outside the package
    all_self_changes: dict[str, list[tuple[str, str]]] = {}

    for src_file, dst_file in file_moves:
        importer_changes, self_changes = _move_single_file(
            src_file, dst_file, lang_name, graph, dry_run)

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
            # Intra-package relative imports (from .foo, from .bar) stay the same
            # because the files move together preserving their relative positions.
            filtered_self = []
            if lang_name == "python":
                for old_str, new_str in self_changes:
                    # Resolve what this import pointed to in the old location
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

    # Report summary — use trailing sep to avoid matching e.g. source/db_operations for source/db
    source_prefix = source_abs + os.sep
    external_changes = {k: v for k, v in all_importer_changes.items()
                        if not k.startswith(source_prefix)}

    total_changes = (len(external_changes) + len(intra_pkg_changes) + len(all_self_changes))
    total_replacements = (sum(len(r) for r in external_changes.values()) +
                          sum(len(r) for r in intra_pkg_changes.values()) +
                          sum(len(r) for r in all_self_changes.values()))

    print(c(f"\n  Move directory: {rel(source_abs)}/ → {rel(dest_abs)}/", "bold"))
    print(c(f"  {len(file_moves)} files in package", "dim"))
    print(c(f"  {total_replacements} import replacements across {total_changes} files\n", "dim"))

    # Show self-import changes (relative imports pointing outside the package)
    if all_self_changes:
        print(c(f"  Own imports ({sum(len(v) for v in all_self_changes.values())} changes across "
                f"{len(all_self_changes)} files):", "cyan"))
        for src_file, changes in sorted(all_self_changes.items()):
            print(f"    {rel(src_file)}:")
            for old, new in changes:
                print(f"      {old}  →  {new}")
        print()

    # Show intra-package absolute import changes
    if intra_pkg_changes:
        print(c(f"  Intra-package imports ({sum(len(v) for v in intra_pkg_changes.values())} changes "
                f"across {len(intra_pkg_changes)} files):", "cyan"))
        for filepath, replacements in sorted(intra_pkg_changes.items()):
            print(f"    {rel(filepath)}:")
            for old, new in replacements:
                print(f"      {old}  →  {new}")
        print()

    # Show external importer changes
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
    # Merge both change sets since they both apply to files inside the moved dir
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
