"""Python import-resolution policy helpers used by dependency detectors."""

from __future__ import annotations

from functools import lru_cache
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
    """Resolve an absolute import within scan root, project root, then src layouts."""
    parts = module_path.split(".")
    for import_root in _import_roots(scan_root.resolve(), get_project_root().resolve()):
        target_base = import_root
        for part in parts:
            target_base = target_base / part
        resolved = try_resolve_path(target_base)
        if resolved:
            return resolved
    return None


def _import_roots(scan_root: Path, project_root: Path) -> tuple[Path, ...]:
    """Directories an absolute import may be rooted at, most specific first.

    Besides the scan and project roots, this covers the PEP 517 ``src`` layout
    (``<root>/src/<pkg>``) and a package nested one level down in a multi-project
    repo (``<root>/<project>/src/<pkg>``), whose modules are otherwise unresolvable
    and get reported as orphaned.
    """
    roots: list[Path] = []
    for base in (scan_root, project_root):
        if base not in roots:
            roots.append(base)
    for base in (scan_root, project_root):
        for src_root in _src_layout_roots(base):
            if src_root not in roots:
                roots.append(src_root)
    return tuple(roots)


@lru_cache(maxsize=32)
def _src_layout_roots(base: Path) -> tuple[Path, ...]:
    """``src`` directories directly under ``base`` or one project level below it."""
    candidates = [base / "src"]
    try:
        children = sorted(child for child in base.iterdir() if child.is_dir())
    except OSError:
        children = []
    candidates.extend(child / "src" for child in children if not child.name.startswith("."))
    return tuple(candidate for candidate in candidates if candidate.is_dir())


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
    "resolve_absolute_import",
    "resolve_python_from_import",
    "resolve_python_import",
    "resolve_relative_import",
    "try_resolve_path",
]
