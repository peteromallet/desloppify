"""Python import graph builder — parses import/from statements, resolves to files."""

import re
from collections import defaultdict
from pathlib import Path

from ....utils import PROJECT_ROOT, resolve_path
from ....detectors.graph import finalize_graph


def build_dep_graph(path: Path) -> dict:
    """Build a dependency graph for Python files.

    Parses:
      - import foo
      - import foo.bar
      - from foo import bar
      - from foo.bar import baz
      - from . import bar  (relative)
      - from .foo import bar  (relative)
      - from ..foo import bar  (relative)

    Returns {resolved_path: {"imports": set, "importers": set, "import_count", "importer_count"}}
    """
    # Single grep pass for all import lines (filtered by --exclude patterns)
    from ....utils import run_grep
    stdout = run_grep(
        ["grep", "-rn", "--include=*.py", "-E",
         r"^\s*(import |from )", str(path)]
    )

    graph: dict[str, dict] = defaultdict(lambda: {
        "imports": set(), "importers": set(), "deferred_imports": set(),
    })

    # Match both relative (from .foo import bar) and absolute (from foo import bar)
    from_re = re.compile(r"^from\s+(\.+\w*(?:\.\w+)*|\w+(?:\.\w+)*)\s+import\s+(.+)")
    import_re = re.compile(r"^import\s+(\w+(?:\.\w+)*)")

    for line in stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        raw_content = parts[2]
        filepath, content = parts[0], raw_content.strip()
        # Indented imports are inside functions/classes (deferred)
        is_deferred = raw_content != raw_content.lstrip()

        source_resolved = resolve_path(filepath)
        graph[source_resolved]  # ensure entry

        # Skip comments
        if content.lstrip().startswith("#"):
            continue

        # from X import Y
        m = from_re.match(content)
        if m:
            module_path = m.group(1)
            import_names = m.group(2)
            targets = _resolve_python_from_import(module_path, import_names, filepath, path)
            for target in targets:
                graph[source_resolved]["imports"].add(target)
                graph[target]["importers"].add(source_resolved)
                if is_deferred:
                    graph[source_resolved]["deferred_imports"].add(target)
            continue

        # import X
        m = import_re.match(content)
        if m:
            module_path = m.group(1)
            target = _resolve_python_import(module_path, filepath, path)
            if target:
                graph[source_resolved]["imports"].add(target)
                graph[target]["importers"].add(source_resolved)
                if is_deferred:
                    graph[source_resolved]["deferred_imports"].add(target)

    return finalize_graph(dict(graph))


def _resolve_python_from_import(module_path: str, import_names: str, source_file: str, scan_root: Path) -> list[str]:
    """Resolve a 'from X import Y' statement to file paths.

    When module_path is dots-only (e.g. 'from . import X, Y'), each imported
    name might be a submodule, so we resolve each name individually.
    Otherwise, resolve the module_path as before.
    """
    source = Path(source_file) if Path(source_file).is_absolute() else PROJECT_ROOT / source_file
    source_dir = source.parent
    scan_root_path = Path(scan_root) if not isinstance(scan_root, Path) else scan_root

    # Check if module_path is dots-only (no remainder after the dots)
    dots_only = all(ch == "." for ch in module_path)

    if dots_only:
        # from . import X, Y  or  from .. import X, Y
        # Each imported name could be a submodule in the base directory
        dots = len(module_path)
        base = source_dir
        for _ in range(dots - 1):
            base = base.parent

        results = []
        # Parse the import names (handle "X, Y" and "X as Z, Y as W")
        names = [n.strip().split()[0] for n in import_names.split(",")]
        for name in names:
            if not name or name.startswith("(") or name.startswith("#"):
                continue
            name = name.strip("()")
            if not name:
                continue
            # Try resolving as a submodule: base/name.py or base/name/__init__.py
            target = _try_resolve_path(base / name)
            if target:
                results.append(target)

        # Also resolve the package __init__.py itself (from . import X can pull from __init__)
        if not results:
            target = _try_resolve_path(base)
            if target:
                results.append(target)
        return results
    else:
        # Normal case: from .foo import bar, from ..foo.bar import baz
        target = _resolve_python_import(module_path, source_file, scan_root_path)
        return [target] if target else []


def _resolve_python_import(module_path: str, source_file: str, scan_root: Path) -> str | None:
    """Resolve a Python import to a file path.

    Handles:
      - Relative imports (starting with .)
      - Absolute imports within the project
    """
    source = Path(source_file) if Path(source_file).is_absolute() else PROJECT_ROOT / source_file
    source_dir = source.parent
    scan_root_path = Path(scan_root) if not isinstance(scan_root, Path) else scan_root

    if module_path.startswith("."):
        return _resolve_relative_import(module_path, source_dir)
    else:
        return _resolve_absolute_import(module_path, scan_root_path)


def _resolve_relative_import(module_path: str, source_dir: Path) -> str | None:
    """Resolve a relative Python import (from . import X, from .foo import X)."""
    # Count leading dots
    dots = 0
    for ch in module_path:
        if ch == ".":
            dots += 1
        else:
            break

    remainder = module_path[dots:]

    # Go up (dots - 1) directories from source_dir
    base = source_dir
    for _ in range(dots - 1):
        base = base.parent

    if remainder:
        parts = remainder.split(".")
        target_base = base
        for part in parts:
            target_base = target_base / part
    else:
        target_base = base

    return _try_resolve_path(target_base)


def _resolve_absolute_import(module_path: str, scan_root: Path) -> str | None:
    """Resolve an absolute Python import within the project."""
    parts = module_path.split(".")
    # Try from scan root
    target_base = scan_root.resolve()
    for part in parts:
        target_base = target_base / part

    resolved = _try_resolve_path(target_base)
    if resolved:
        return resolved

    # Try from project root
    target_base = PROJECT_ROOT
    for part in parts:
        target_base = target_base / part

    return _try_resolve_path(target_base)


def _try_resolve_path(target_base: Path) -> str | None:
    """Try to resolve a module base path to an actual file."""
    # foo.py
    candidate = Path(str(target_base) + ".py")
    if candidate.is_file():
        return str(candidate.resolve())

    # foo/__init__.py
    candidate = target_base / "__init__.py"
    if candidate.is_file():
        return str(candidate.resolve())

    # foo/ (directory with __init__.py)
    if target_base.is_dir():
        init = target_base / "__init__.py"
        if init.is_file():
            return str(init.resolve())

    return None
