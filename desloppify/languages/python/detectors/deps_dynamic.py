"""Dynamic import discovery for Python dependency hints."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from .deps_resolution import resolve_python_import

logger = logging.getLogger(__name__)


def find_python_dynamic_imports(path: Path, extensions: list[str]) -> set[str]:
    """Find module specifiers referenced by ``importlib.import_module`` calls."""
    del extensions
    targets: set[str] = set()
    for py_file in path.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            logger.debug(
                "Skipping unreadable file %s in dynamic import scan: %s",
                py_file,
                exc,
            )
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr == "import_module"
                and isinstance(func.value, ast.Name)
                and func.value.id == "importlib"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                continue

            spec = node.args[0].value
            resolved = resolve_python_import(spec, str(py_file), path)
            if resolved:
                targets.add(resolved)
            else:
                targets.add(spec)
    return targets


__all__ = ["find_python_dynamic_imports"]
