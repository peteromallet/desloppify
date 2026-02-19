"""Architecture guardrails for detector/language boundaries."""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DETECTORS_DIR = _REPO_ROOT / "desloppify" / "engine" / "detectors"
_DOT_LANG_PATTERN = re.compile(r"\.lang\.")


def _detector_files() -> list[Path]:
    return sorted(
        p
        for p in _DETECTORS_DIR.rglob("*.py")
        if p.is_file() and p.name != "__init__.py"
    )


def test_detectors_do_not_import_language_modules() -> None:
    offenders: list[str] = []

    for file_path in _detector_files():
        tree = ast.parse(file_path.read_text(), filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name == "desloppify.languages" or name.startswith("desloppify.languages."):
                        offenders.append(f"{file_path}:{node.lineno} imports {name}")
                continue

            if not isinstance(node, ast.ImportFrom):
                continue

            module = node.module or ""
            level = node.level or 0
            if module == "desloppify.languages" or module.startswith("desloppify.languages."):
                offenders.append(f"{file_path}:{node.lineno} imports from {module}")
                continue

            relative_module = "." * level + module
            if relative_module.startswith("..lang") or relative_module.startswith(
                ".lang"
            ):
                offenders.append(
                    f"{file_path}:{node.lineno} imports from relative module {relative_module}"
                )

    assert not offenders, "\n".join(offenders)


def test_detectors_do_not_use_dynamic_lang_import_strings() -> None:
    offenders: list[str] = []

    for file_path in _detector_files():
        tree = ast.parse(file_path.read_text(), filename=str(file_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if _DOT_LANG_PATTERN.search(node.value):
                offenders.append(
                    f"{file_path}:{node.lineno} contains string {node.value!r}"
                )

    assert not offenders, "\n".join(offenders)
