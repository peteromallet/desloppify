"""Python import-resolution policy helpers used by dependency detectors."""

from __future__ import annotations

from pathlib import Path

from desloppify.base.discovery.paths import get_project_root


def resolve_python_from_import(
    module_path: str,
    import_names: str,
    source_file: str,
    scan_root: Path,
) -> list[str]:
    """Resolve a ``from X import Y`` statement to one or more file paths."""
    source = (
        Path(source_file)
        if Path(source_file).is_absolute()
        else get_project_root() / source_file
    )
    source_dir = source.parent
    scan_root_path = Path(scan_root) if not isinstance(scan_root, Path) else scan_root

    dots_only = all(ch == "." for ch in module_path)
    if dots_only:
        dots = len(module_path)
        base = source_dir
        for _ in range(dots - 1):
            base = base.parent

        results: list[str] = []
        names = [name.strip().split()[0] for name in import_names.split(",")]
        for name in names:
            if not name or name.startswith("(") or name.startswith("#"):
                continue
            cleaned = name.strip("()")
            if not cleaned:
                continue
            target = try_resolve_path(base / cleaned)
            if target:
                results.append(target)

        if not results:
            target = try_resolve_path(base)
            if target:
                results.append(target)
        return results

    results = []
    target = resolve_python_import(module_path, source_file, scan_root_path)
    if target and import_names:
        names = [name.strip().split()[0] for name in import_names.split(",")]
        for name in names:
            cleaned = name.strip("()")
            if not cleaned:
                continue
            submodule = resolve_python_import(
                f"{module_path}.{cleaned}",
                source_file,
                scan_root_path,
            )
            if submodule:
                results.append(submodule)
    if target:
        results.append(target)
    return results


def resolve_python_import(
    module_path: str,
    source_file: str,
    scan_root: Path,
) -> str | None:
    """Resolve a Python import module path to a project file."""
    source = (
        Path(source_file)
        if Path(source_file).is_absolute()
        else get_project_root() / source_file
    )
    source_dir = source.parent
    scan_root_path = Path(scan_root) if not isinstance(scan_root, Path) else scan_root
    if module_path.startswith("."):
        return resolve_relative_import(module_path, source_dir)
    return resolve_absolute_import(module_path, scan_root_path)


def resolve_relative_import(module_path: str, source_dir: Path) -> str | None:
    """Resolve a relative import path starting from the source file directory."""
    dots = 0
    for ch in module_path:
        if ch == ".":
            dots += 1
        else:
            break
    remainder = module_path[dots:]

    base = source_dir
    for _ in range(dots - 1):
        base = base.parent

    target_base = base
    if remainder:
        for part in remainder.split("."):
            target_base = target_base / part
    return try_resolve_path(target_base)


def resolve_absolute_import(module_path: str, scan_root: Path) -> str | None:
    """Resolve an absolute import to a project file.

    Each candidate source root (see :func:`candidate_source_roots`) is tried in
    priority order, covering both the flat layout (``<root>/<pkg>``) and the
    ``src`` layout (``<root>/src/<pkg>``) recommended by the Python Packaging
    Authority. Without the ``src`` candidates, a ``from pkg.sub import x``
    statement in a ``src``-layout project resolves to nothing, so ``pkg/sub.py``
    is recorded with zero importers and misreported as orphaned/uncoupled.
    """
    parts = module_path.split(".")
    for root in candidate_source_roots(scan_root):
        target_base = root
        for part in parts:
            target_base = target_base / part
        resolved = try_resolve_path(target_base)
        if resolved:
            return resolved
    return None


def candidate_source_roots(scan_root: Path) -> list[Path]:
    """Return the roots an absolute import may resolve against, in priority order.

    The scan root and the project root are each tried with and without a ``src``
    prefix, so absolute imports resolve under both the flat and ``src`` layouts.
    The flat roots are tried before the ``src`` roots, so this is strictly
    additive: any import that resolved before resolves to the same file, and only
    previously-unresolved ``src``-layout imports gain an edge. Duplicate roots
    (common when the scan root is the project root) are collapsed.
    """
    flat_roots = [scan_root.resolve(), get_project_root()]
    roots: list[Path] = []
    for candidate in (*flat_roots, *(root / "src" for root in flat_roots)):
        if candidate not in roots:
            roots.append(candidate)
    return roots


def try_resolve_path(target_base: Path) -> str | None:
    """Try to resolve module base to ``.py`` or package ``__init__.py`` path."""
    candidate = Path(str(target_base) + ".py")
    if candidate.is_file():
        return str(candidate.resolve())

    candidate = target_base / "__init__.py"
    if candidate.is_file():
        return str(candidate.resolve())

    if target_base.is_dir():
        init_path = target_base / "__init__.py"
        if init_path.is_file():
            return str(init_path.resolve())

    return None


__all__ = [
    "candidate_source_roots",
    "resolve_absolute_import",
    "resolve_python_from_import",
    "resolve_python_import",
    "resolve_relative_import",
    "try_resolve_path",
]
