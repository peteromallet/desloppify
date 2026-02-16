"""Developer utilities."""

from __future__ import annotations

import ast
import keyword
import re

from ..utils import PROJECT_ROOT, colorize, safe_write_text


def cmd_dev(args) -> None:
    """Dispatch developer subcommands."""
    action = getattr(args, "dev_action", None)
    if action == "scaffold-lang":
        try:
            _cmd_scaffold_lang(args)
        except ValueError as ex:
            raise SystemExit(colorize(str(ex), "red")) from ex
        return
    print(colorize("Unknown dev action. Use `desloppify dev scaffold-lang`.", "red"))


def _normalize_lang_name(raw: str) -> str:
    name = raw.strip().lower().replace("-", "_")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError("language name must match [a-z][a-z0-9_]*")
    if keyword.iskeyword(name):
        raise ValueError(f"language name cannot be a Python keyword: {name}")
    return name


def _normalize_extensions(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for val in values or []:
        ext = val.strip()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        if not re.fullmatch(r"\.[a-z0-9]+", ext):
            raise ValueError(f"invalid extension: {val!r}")
        out.append(ext)
    if not out:
        raise ValueError("at least one --extension is required")
    seen: set[str] = set()
    deduped: list[str] = []
    for ext in out:
        if ext not in seen:
            seen.add(ext)
            deduped.append(ext)
    return deduped


def _normalize_markers(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for val in values or []:
        marker = val.strip()
        if marker and marker not in out:
            out.append(marker)
    return out


def _class_name(lang_name: str) -> str:
    return "".join(part.capitalize() for part in lang_name.split("_")) + "Config"


def _template_files(
    lang_name: str,
    extensions: list[str],
    markers: list[str],
    default_src: str,
) -> dict[str, str]:
    class_name = _class_name(lang_name)
    ext_repr = repr(extensions)
    marker_repr = repr(markers)
    ext_sample = extensions[0]
    return {
        "__init__.py": f'''"""Language configuration for {lang_name}."""
from __future__ import annotations
from pathlib import Path
from .. import register_lang
from ..base import DetectorPhase, LangConfig
from ...utils import find_source_files
from ...zones import COMMON_ZONE_RULES
from .commands import get_detect_commands
from .phases import _phase_placeholder
def _find_files(path: Path) -> list[str]:
    return find_source_files(path, {ext_repr})
def _build_dep_graph(path: Path) -> dict:
    from .detectors.deps import build_dep_graph
    return build_dep_graph(path)
@register_lang("{lang_name}")
class {class_name}(LangConfig):
    def __init__(self):
        super().__init__(
            name={lang_name!r},
            extensions={ext_repr},
            exclusions=["node_modules", ".venv"],
            default_src={default_src!r},
            build_dep_graph=_build_dep_graph,
            entry_patterns=[],
            barrel_names=set(),
            phases=[DetectorPhase("Placeholder", _phase_placeholder)],
            detect_commands=get_detect_commands(),
            file_finder=_find_files,
            detect_markers={marker_repr},
            test_file_extensions={ext_repr},
            zone_rules=COMMON_ZONE_RULES,
        )
''',
        "phases.py": '''"""Phase runners for language plugin scaffolding."""
from __future__ import annotations
from pathlib import Path
from ..base import LangConfig
def _phase_placeholder(_path: Path, _lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    return [], {}
''',
        "commands.py": f'''"""Detect command registry for language plugin scaffolding."""
from __future__ import annotations
from typing import TYPE_CHECKING, Callable
from ...utils import c
if TYPE_CHECKING:
    import argparse
def cmd_placeholder(_args: argparse.Namespace) -> None:
    print(c("{lang_name}: placeholder detector command (not implemented)", "yellow"))
def get_detect_commands() -> dict[str, Callable[..., None]]:
    return {{"placeholder": cmd_placeholder}}
''',
        "extractors.py": '''"""Extractors for language plugin scaffolding."""
from __future__ import annotations
def extract_functions(_path) -> list:
    return []
''',
        "move.py": '''"""Move helpers for language plugin scaffolding."""
from __future__ import annotations
VERIFY_HINT = "desloppify detect deps"
def find_replacements(_source_abs: str, _dest_abs: str, _graph: dict) -> dict[str, list[tuple[str, str]]]:
    return {}
def find_self_replacements(_source_abs: str, _dest_abs: str, _graph: dict) -> list[tuple[str, str]]:
    return []
''',
        "review.py": f'''"""Review guidance hooks for language plugin scaffolding."""
from __future__ import annotations
REVIEW_GUIDANCE = {{"patterns": [], "auth": [], "naming": "{lang_name} naming guidance placeholder"}}
def module_patterns(_content: str) -> list[str]:
    return []
def api_surface(_file_contents: dict[str, str]) -> dict:
    return {{}}
''',
        "test_coverage.py": '''"""Test coverage hooks for language plugin scaffolding."""
from __future__ import annotations
import re
ASSERT_PATTERNS: list[re.Pattern[str]] = []
MOCK_PATTERNS: list[re.Pattern[str]] = []
SNAPSHOT_PATTERNS: list[re.Pattern[str]] = []
TEST_FUNCTION_RE = re.compile(r"$^")
BARREL_BASENAMES: set[str] = set()
def has_testable_logic(_filepath: str, _content: str) -> bool:
    return True
def resolve_import_spec(_spec: str, _test_path: str, _production_files: set[str]) -> str | None:
    return None
''',
        "detectors/__init__.py": "",
        "detectors/deps.py": '''"""Dependency graph builder scaffold."""
from __future__ import annotations
from pathlib import Path
def build_dep_graph(_path: Path) -> dict:
    return {}
''',
        "fixers/__init__.py": "",
        "tests/__init__.py": "",
        "tests/test_init.py": f'''"""Scaffold sanity tests for the generated language plugin."""
from __future__ import annotations
from desloppify.lang.{lang_name} import {class_name}
def test_config_name():
    cfg = {class_name}()
    assert cfg.name == {lang_name!r}
def test_config_extensions_non_empty():
    cfg = {class_name}()
    assert {ext_sample!r} in cfg.extensions
def test_detect_commands_non_empty():
    cfg = {class_name}()
    assert cfg.detect_commands
''',
    }


def _render_array(items: list[str]) -> str:
    return ", ".join(repr(x) for x in items)


def _append_toml_array_item(text: str, key: str, value: str) -> str:
    pattern = re.compile(
        rf"(^\s*{re.escape(key)}\s*=\s*\[)(.*?)(\]\s*$)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return text

    raw = match.group(2).strip()
    parsed = ast.literal_eval("[" + raw + "]") if raw else []
    if not isinstance(parsed, list):
        return text
    if value in parsed:
        return text

    parsed.append(value)
    replacement = f"{match.group(1)}{_render_array(parsed)}{match.group(3)}"
    return text[:match.start()] + replacement + text[match.end():]


def _wire_pyproject(lang_name: str) -> bool:
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    if not pyproject_path.is_file():
        return False

    original = pyproject_path.read_text()
    updated = original
    updated = _append_toml_array_item(
        updated,
        "exclude",
        f"desloppify.lang.{lang_name}.tests*",
    )
    updated = _append_toml_array_item(
        updated,
        "testpaths",
        f"desloppify/lang/{lang_name}/tests",
    )

    if updated != original:
        safe_write_text(pyproject_path, updated)
        return True
    return False


def _cmd_scaffold_lang(args) -> None:
    raw_name = getattr(args, "name", "")
    lang_name = _normalize_lang_name(raw_name)
    extensions = _normalize_extensions(getattr(args, "extension", None))
    markers = _normalize_markers(getattr(args, "marker", None))
    default_src = getattr(args, "default_src", "src") or "src"
    force = bool(getattr(args, "force", False))
    wire_pyproject = bool(getattr(args, "wire_pyproject", True))

    lang_dir = PROJECT_ROOT / "desloppify" / "lang" / lang_name
    if lang_dir.exists() and not force:
        raise SystemExit(
            colorize(
                f"Language directory already exists: {lang_dir}. Use --force to overwrite.",
                "red",
            )
        )

    files = _template_files(lang_name, extensions, markers, default_src)
    for rel_path, content in files.items():
        target = lang_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not force:
            continue
        safe_write_text(target, content)

    wired = _wire_pyproject(lang_name) if wire_pyproject else False

    print(colorize(f"Scaffolded language plugin: {lang_name}", "green"))
    print(f"  Path: {lang_dir}")
    print(f"  Extensions: {', '.join(extensions)}")
    print(f"  Markers: {', '.join(markers) if markers else '(none)'}")
    print(f"  pyproject.toml updated: {'yes' if wired else 'no'}")
    print(colorize("  Next: implement real phases/commands/detectors and run pytest.", "dim"))
