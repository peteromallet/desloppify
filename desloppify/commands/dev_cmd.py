"""Developer utilities."""

from __future__ import annotations

import ast
import keyword
import re
from pathlib import Path

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
        "__init__.py": f'''"""Language configuration for {lang_name}."""\n\n'''
        "from __future__ import annotations\n\n"
        "from pathlib import Path\n\n"
        "from .. import register_lang\n"
        "from ..base import DetectorPhase, LangConfig\n"
        "from ...utils import find_source_files\n"
        "from ...zones import COMMON_ZONE_RULES\n"
        "from .commands import get_detect_commands\n"
        "from .extractors import extract_functions\n"
        "from .phases import _phase_placeholder\n"
        "from .review import (\n"
        "    LOW_VALUE_PATTERN,\n"
        "    MIGRATION_MIXED_EXTENSIONS,\n"
        "    MIGRATION_PATTERN_PAIRS,\n"
        "    REVIEW_GUIDANCE,\n"
        "    api_surface,\n"
        "    module_patterns,\n"
        ")\n\n\n"
        f"{lang_name.upper()}_ZONE_RULES = COMMON_ZONE_RULES\n\n\n"
        "def _find_files(path: Path) -> list[str]:\n"
        f"    return find_source_files(path, {ext_repr})\n\n\n"
        "def _build_dep_graph(path: Path) -> dict:\n"
        "    from .detectors.deps import build_dep_graph\n\n"
        "    return build_dep_graph(path)\n\n\n"
        f'@register_lang("{lang_name}")\n'
        f"class {class_name}(LangConfig):\n"
        "    def __init__(self):\n"
        "        super().__init__(\n"
        f"            name={lang_name!r},\n"
        f"            extensions={ext_repr},\n"
        '            exclusions=["node_modules", ".venv"],\n'
        f"            default_src={default_src!r},\n"
        "            build_dep_graph=_build_dep_graph,\n"
        "            entry_patterns=[],\n"
        "            barrel_names=set(),\n"
        "            phases=[DetectorPhase(\"Placeholder\", _phase_placeholder)],\n"
        "            fixers={},\n"
        "            get_area=lambda filepath: filepath.split(\"/\")[0],\n"
        "            detect_commands=get_detect_commands(),\n"
        "            boundaries=[],\n"
        '            typecheck_cmd="",\n'
        "            file_finder=_find_files,\n"
        f"            detect_markers={marker_repr},\n"
        '            external_test_dirs=["tests", "test"],\n'
        f"            test_file_extensions={ext_repr},\n"
        "            review_module_patterns_fn=module_patterns,\n"
        "            review_api_surface_fn=api_surface,\n"
        "            review_guidance=REVIEW_GUIDANCE,\n"
        "            review_low_value_pattern=LOW_VALUE_PATTERN,\n"
        "            holistic_review_dimensions=[\"cross_module_architecture\", \"test_strategy\"],\n"
        "            migration_pattern_pairs=MIGRATION_PATTERN_PAIRS,\n"
        "            migration_mixed_extensions=MIGRATION_MIXED_EXTENSIONS,\n"
        "            extract_functions=extract_functions,\n"
        f"            zone_rules={lang_name.upper()}_ZONE_RULES,\n"
        "        )\n",
        "phases.py": '''"""Phase runners for language plugin scaffolding."""\n\n'''
        "from __future__ import annotations\n\n"
        "from pathlib import Path\n\n"
        "from ..base import LangConfig\n\n\n"
        "def _phase_placeholder(_path: Path, _lang: LangConfig) -> tuple[list[dict], dict[str, int]]:\n"
        '    """Placeholder phase. Replace with real detector orchestration."""\n'
        "    return [], {}\n",
        "commands.py": '''"""Detect command registry for language plugin scaffolding."""\n\n'''
        "from __future__ import annotations\n\n"
        "from typing import TYPE_CHECKING, Callable\n\n"
        "from ...utils import c\n\n"
        "if TYPE_CHECKING:\n"
        "    import argparse\n\n\n"
        "def cmd_placeholder(_args: argparse.Namespace) -> None:\n"
        f"    print(c(\"{lang_name}: placeholder detector command (not implemented)\", \"yellow\"))\n\n\n"
        "def get_detect_commands() -> dict[str, Callable[..., None]]:\n"
        '    return {"placeholder": cmd_placeholder}\n',
        "extractors.py": '''"""Extractors for language plugin scaffolding."""\n\n'''
        "from __future__ import annotations\n\n"
        "from pathlib import Path\n\n\n"
        "def extract_functions(_path: Path) -> list:\n"
        '    """Return function-like items for duplicate/signature detectors."""\n'
        "    return []\n",
        "move.py": '''"""Move helpers for language plugin scaffolding."""\n\n'''
        "from __future__ import annotations\n\n\n"
        'VERIFY_HINT = "desloppify detect deps"\n\n\n'
        "def find_replacements(\n"
        "    _source_abs: str, _dest_abs: str, _graph: dict\n"
        ") -> dict[str, list[tuple[str, str]]]:\n"
        "    return {}\n\n\n"
        "def find_self_replacements(\n"
        "    _source_abs: str, _dest_abs: str, _graph: dict\n"
        ") -> list[tuple[str, str]]:\n"
        "    return []\n",
        "review.py": '''"""Review guidance hooks for language plugin scaffolding."""\n\n'''
        "from __future__ import annotations\n\n"
        "import re\n\n\n"
        "REVIEW_GUIDANCE = {\n"
        '    "patterns": [],\n'
        '    "auth": [],\n'
        f'    "naming": "{lang_name} naming guidance placeholder",\n'
        "}\n\n"
        "MIGRATION_PATTERN_PAIRS: list[tuple[str, object, object]] = []\n"
        "MIGRATION_MIXED_EXTENSIONS: set[str] = set()\n"
        'LOW_VALUE_PATTERN = re.compile(r"$^")\n\n\n'
        "def module_patterns(_content: str) -> list[str]:\n"
        "    return []\n\n\n"
        "def api_surface(_file_contents: dict[str, str]) -> dict:\n"
        "    return {}\n",
        "test_coverage.py": '''"""Test coverage hooks for language plugin scaffolding."""\n\n'''
        "from __future__ import annotations\n\n"
        "import re\n\n\n"
        "ASSERT_PATTERNS: list[re.Pattern[str]] = []\n"
        "MOCK_PATTERNS: list[re.Pattern[str]] = []\n"
        "SNAPSHOT_PATTERNS: list[re.Pattern[str]] = []\n"
        'TEST_FUNCTION_RE = re.compile(r"$^")\n'
        "BARREL_BASENAMES: set[str] = set()\n\n\n"
        "def has_testable_logic(_filepath: str, _content: str) -> bool:\n"
        "    return True\n\n\n"
        "def resolve_import_spec(\n"
        "    _spec: str, _test_path: str, _production_files: set[str]\n"
        ") -> str | None:\n"
        "    return None\n\n\n"
        "def resolve_barrel_reexports(_filepath: str, _production_files: set[str]) -> set[str]:\n"
        "    return set()\n\n\n"
        "def parse_test_import_specs(_content: str) -> list[str]:\n"
        "    return []\n\n\n"
        "def map_test_to_source(_test_path: str, _production_set: set[str]) -> str | None:\n"
        "    return None\n\n\n"
        "def strip_test_markers(_basename: str) -> str | None:\n"
        "    return None\n\n\n"
        "def strip_comments(content: str) -> str:\n"
        "    return content\n",
        "detectors/__init__.py": "",
        "detectors/deps.py": '''"""Dependency graph builder scaffold."""\n\n'''
        "from __future__ import annotations\n\n"
        "from pathlib import Path\n\n\n"
        "def build_dep_graph(_path: Path) -> dict:\n"
        "    return {}\n",
        "fixers/__init__.py": "",
        "tests/__init__.py": "",
        "tests/test_init.py": '''"""Scaffold sanity tests for the generated language plugin."""\n\n'''
        "from __future__ import annotations\n\n"
        f"from desloppify.lang.{lang_name} import {class_name}\n\n\n"
        "def test_config_name():\n"
        f"    cfg = {class_name}()\n"
        f"    assert cfg.name == {lang_name!r}\n\n\n"
        "def test_config_extensions_non_empty():\n"
        f"    cfg = {class_name}()\n"
        f"    assert {ext_sample!r} in cfg.extensions\n\n\n"
        "def test_detect_commands_non_empty():\n"
        f"    cfg = {class_name}()\n"
        "    assert cfg.detect_commands\n",
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
