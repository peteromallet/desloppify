"""Unused import fixer: removes unused symbols from import statements."""

import re
from collections import defaultdict

from desloppify.languages.typescript.fixers.common import (
    _collect_import_statement,
    apply_fixer,
)


def fix_unused_imports(entries: list[dict], *, dry_run: bool = False) -> list[dict]:
    """Remove unused imports from source files."""
    import_entries = [e for e in entries if e["category"] == "imports"]

    def transform(
        lines: list[str], file_entries: list[dict[str, object]]
    ) -> tuple[list[str], list[str]]:
        unused_symbols = {e["name"] for e in file_entries}
        unused_by_line: dict[int, list[str]] = defaultdict(list)
        for e in file_entries:
            unused_by_line[e["line"]].append(e["name"])

        new_lines, removed_symbols = _process_file_lines(
            lines, unused_symbols, unused_by_line
        )
        removed = []
        for e in file_entries:
            name = e["name"]
            if name in removed_symbols and name not in removed:
                removed.append(name)
        return new_lines, removed

    return apply_fixer(import_entries, transform, dry_run=dry_run)


def _process_file_lines(
    lines: list[str], unused_symbols: set[str], unused_by_line: dict[int, list[str]]
) -> tuple[list[str], set[str]]:
    """Process file lines, removing unused imports. Returns new lines + removed symbols."""
    result = []
    removed_symbols: set[str] = set()
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped.startswith("import "):
            result.append(line)
            i += 1
            continue

        import_lines, end_idx = _collect_import_statement(lines, i)
        processed_lines = _process_import_statement(
            import_lines,
            import_start=i,
            unused_symbols=unused_symbols,
            unused_by_line=unused_by_line,
        )
        replacement_lines, removed_from_stmt = processed_lines
        removed_symbols.update(removed_from_stmt)
        if replacement_lines:
            result.extend(replacement_lines)
        i = end_idx + 1

    return result, removed_symbols


def _process_import_statement(
    import_lines: list[str],
    *,
    import_start: int,
    unused_symbols: set[str],
    unused_by_line: dict[int, list[str]],
) -> tuple[list[str], set[str]]:
    lineno = import_start + 1  # 1-indexed
    if "(entire import)" in unused_symbols and any(
        "(entire import)" in unused_by_line.get(ln, [])
        for ln in range(lineno, lineno + len(import_lines))
    ):
        return [], {"(entire import)"}

    symbols_on_this_import: set[str] = set()
    for ln in range(lineno, lineno + len(import_lines)):
        for sym in unused_by_line.get(ln, []):
            if sym != "(entire import)":
                symbols_on_this_import.add(sym)

    if not symbols_on_this_import:
        return import_lines, set()

    full_import = "".join(import_lines)
    cleaned, removed_from_stmt = _remove_symbols_from_import(
        full_import, symbols_on_this_import
    )
    if cleaned is None:
        return [], removed_from_stmt
    if not removed_from_stmt:
        return import_lines, set()
    return [cleaned], removed_from_stmt


def _normalize_binding_name(token: str) -> str:
    normalized = token.strip().rstrip(",")
    if normalized.startswith("type "):
        normalized = normalized[len("type ") :].strip()
    return normalized


def _binding_symbol_names(binding: str) -> set[str]:
    binding = binding.strip().rstrip(",")
    if not binding:
        return set()
    parts = re.split(r"\s+as\s+", binding, maxsplit=1)
    names = {_normalize_binding_name(parts[0])}
    if len(parts) == 2:
        names.add(_normalize_binding_name(parts[1]))
    return {n for n in names if n and n != "*"}


def _remove_symbols_from_import(
    import_stmt: str, symbols_to_remove: set[str]
) -> tuple[str | None, set[str]]:
    """Remove specific symbols from an import statement.

    Returns `(cleaned import or None, removed symbols)`.
    """
    stmt = import_stmt.strip()

    from_match = re.search(
        r"""from\s+(?P<module>['"][^'"]+['"])(?P<attrs>\s+(?:assert|with)\s*\{.*?\})?\s*;?(?P<trailing>\s*(?://.*|/\*.*?\*/\s*)?)$""",
        stmt,
        re.DOTALL,
    )
    if not from_match:
        return import_stmt, set()

    module_part = from_match.group("module")
    attrs = from_match.group("attrs") or ""
    trailing = (from_match.group("trailing") or "").strip()
    from_clause = f"from {module_part}{attrs};"
    if trailing:
        from_clause += f" {trailing}"
    before_from = stmt[: from_match.start()].strip()

    type_prefix = ""
    if before_from.startswith("import type"):
        type_prefix = "type "
        before_from = before_from[len("import type") :].strip()
    elif before_from.startswith("import"):
        before_from = before_from[len("import") :].strip()
    else:
        return import_stmt, set()

    default_import = None
    namespace_import = None
    named_imports = []

    brace_match = re.search(r"\{([^}]*)\}", before_from, re.DOTALL)
    if brace_match:
        named_str = brace_match.group(1)
        named_imports = [n.strip() for n in named_str.split(",") if n.strip()]
        before_brace = before_from[: brace_match.start()].strip().rstrip(",").strip()
        if before_brace:
            default_import = before_brace
    else:
        bare_import = before_from.strip().rstrip(",").strip()
        if "," in bare_import:
            first, second = [part.strip() for part in bare_import.split(",", 1)]
            default_import = first or None
            namespace_import = second or None
        elif bare_import.startswith("* as "):
            namespace_import = bare_import
        else:
            default_import = bare_import or None

    removed_symbols: set[str] = set()

    default_names = _binding_symbol_names(default_import or "")
    remove_default = bool(default_names & symbols_to_remove)
    if remove_default:
        removed_symbols.update(default_names & symbols_to_remove)

    namespace_names = _binding_symbol_names(namespace_import or "")
    remove_namespace = bool(namespace_names & symbols_to_remove)
    if remove_namespace:
        removed_symbols.update(namespace_names & symbols_to_remove)

    remaining_named = []
    for named in named_imports:
        named_names = _binding_symbol_names(named)
        matched = named_names & symbols_to_remove
        if matched:
            removed_symbols.update(matched)
            continue
        remaining_named.append(named)

    if not removed_symbols:
        return import_stmt, set()

    new_default = None if remove_default else default_import
    new_namespace = None if remove_namespace else namespace_import
    new_named = remaining_named

    if not new_default and not new_namespace and not new_named:
        return None, removed_symbols

    parts = []
    if new_default:
        parts.append(new_default)
    if new_namespace:
        parts.append(new_namespace)
    if new_named:
        if len(new_named) <= 3:
            parts.append("{ " + ", ".join(new_named) + " }")
        else:
            inner = ",\n  ".join(new_named)
            parts.append("{\n  " + inner + "\n}")

    indent = ""
    for ch in import_stmt:
        if ch in " \t":
            indent += ch
        else:
            break

    return (
        f"{indent}import {type_prefix}{', '.join(parts)} {from_clause}\n",
        removed_symbols,
    )
