"""Discover Python source roots declared by the project layout.

Projects that keep importable code in a subdirectory of the repo root (e.g.
``scripts/`` run with ``PYTHONPATH=scripts``, or ``src/`` layouts) declare
those roots in ``pyproject.toml``. Import resolution honors the declared
roots so absolute imports resolve to files the same way they do at runtime.
Without this, every ``import mypkg`` in such a project fails to resolve:
the dependency graph reports 0 importers everywhere and the test-coverage
mapper marks fully-tested modules as untested.

Recognized declarations (first match wins per root, duplicates dropped):

- ``[tool.desloppify] python_source_roots = ["scripts"]`` (explicit override)
- ``[tool.pytest.ini_options] pythonpath = ["scripts", ...]``
- ``[tool.mypy] mypy_path = "scripts"``
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path


def _as_list(value: object) -> list[str]:
    """Normalize a TOML string (``:``/``,`` separated) or list into a list."""
    if isinstance(value, str):
        parts = value.replace(",", ":").split(":")
        return [part.strip() for part in parts if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


@lru_cache(maxsize=None)
def declared_source_roots(project_root: str) -> tuple[str, ...]:
    """Return source-root directories (relative to *project_root*) declared
    in ``pyproject.toml``.

    Only safe relative roots are returned: absolute paths, parent traversal,
    and ``.`` (the project root itself, already tried by resolvers) are
    dropped. Returns ``()`` when no pyproject exists or nothing is declared.
    """
    pyproject = Path(project_root) / "pyproject.toml"
    if not pyproject.is_file():
        return ()
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return ()

    roots: list[str] = []
    explicit = tool.get("desloppify")
    if isinstance(explicit, dict):
        roots += _as_list(explicit.get("python_source_roots"))
    pytest_tool = tool.get("pytest")
    if isinstance(pytest_tool, dict):
        ini_options = pytest_tool.get("ini_options")
        if isinstance(ini_options, dict):
            roots += _as_list(ini_options.get("pythonpath"))
    mypy_tool = tool.get("mypy")
    if isinstance(mypy_tool, dict):
        roots += _as_list(mypy_tool.get("mypy_path"))

    cleaned: list[str] = []
    seen: set[str] = set()
    for root in roots:
        root = root.strip().rstrip("/")
        if not root or root == "." or root.startswith(("/", "..", "~")):
            continue
        if root not in seen:
            seen.add(root)
            cleaned.append(root)
    return tuple(cleaned)


__all__ = ["declared_source_roots"]
