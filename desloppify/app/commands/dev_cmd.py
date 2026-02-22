"""Developer utilities."""

from __future__ import annotations

import argparse
import ast
import keyword
import re
import sys

from desloppify.app.commands.dev_scaffold_templates import build_scaffold_files
from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.utils import colorize, safe_write_text


def cmd_dev(args: argparse.Namespace) -> None:
    """Dispatch developer subcommands."""
    action = getattr(args, "dev_action", None)
    if action == "scaffold-lang":
        try:
            _cmd_scaffold_lang(args)
        except ValueError as ex:
            raise SystemExit(colorize(str(ex), "red")) from ex
        return
    print(
        colorize("Unknown dev action. Use `desloppify dev scaffold-lang`.", "red"),
        file=sys.stderr,
    )
    sys.exit(1)


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
    return build_scaffold_files(
        lang_name=lang_name,
        class_name=class_name,
        extensions=extensions,
        markers=markers,
        default_src=default_src,
    )


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
    return text[: match.start()] + replacement + text[match.end() :]


def _wire_pyproject(lang_name: str) -> bool:
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    if not pyproject_path.is_file():
        return False

    original = pyproject_path.read_text()
    updated = original
    updated = _append_toml_array_item(
        updated,
        "testpaths",
        f"desloppify/languages/{lang_name}/tests",
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

    lang_dir = PROJECT_ROOT / "desloppify" / "languages" / lang_name
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
    print(
        colorize(
            "  Next: implement real phases/commands/detectors and run pytest.", "dim"
        )
    )
