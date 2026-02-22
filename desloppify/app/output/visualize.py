"""Codebase treemap visualization with HTML output and LLM-readable tree text."""

import argparse
import json
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desloppify.app.output._viz_cmd_context import load_cmd_context
from desloppify.app.output.tree_text import render_tree_lines
from desloppify.core.fallbacks import log_best_effort_failure
from desloppify.state import get_objective_score, get_overall_score, get_strict_score
from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.file_discovery import rel
from desloppify.utils import colorize, safe_write_text

D3_CDN_URL = "https://d3js.org/d3.v7.min.js"
logger = logging.getLogger(__name__)


__all__ = ["D3_CDN_URL", "cmd_viz", "cmd_tree"]


def _resolve_visualization_lang(path: Path, lang):
    """Resolve language config for visualization if not already provided."""
    if lang:
        return lang
    from desloppify.languages import auto_detect_lang, get_lang

    search_roots = [path if path.is_dir() else path.parent]
    search_roots.extend(search_roots[0].parents)
    for root in search_roots:
        detected = auto_detect_lang(root)
        if detected:
            return get_lang(detected)
    return None


def _fallback_source_files(path: Path) -> list[str]:
    """Collect source files using extensions from all registered language plugins."""
    from desloppify.languages import available_langs, get_lang
    from desloppify.utils import find_source_files

    extensions: set[str] = set()
    for lang_name in available_langs():
        cfg = get_lang(lang_name)
        extensions.update(cfg.extensions)
    if not extensions:
        return []
    return find_source_files(path, sorted(extensions))


def _collect_file_data(path: Path, lang=None) -> list[dict]:
    """Collect LOC for all source files using the language's file finder."""
    resolved_lang = _resolve_visualization_lang(path, lang)
    if resolved_lang and resolved_lang.file_finder:
        source_files = resolved_lang.file_finder(path)
    else:
        source_files = _fallback_source_files(path)
    files = []
    for filepath in source_files:
        try:
            p = (
                Path(filepath)
                if Path(filepath).is_absolute()
                else PROJECT_ROOT / filepath
            )
            content = p.read_text()
            loc = len(content.splitlines())
            files.append(
                {
                    "path": rel(filepath),
                    "abs_path": str(p.resolve()),
                    "loc": loc,
                }
            )
        except (OSError, UnicodeDecodeError) as exc:
            log_best_effort_failure(
                logger, f"read visualization source file {filepath}", exc
            )
            continue
    return files


def _build_tree(files: list[dict], dep_graph: dict, findings_by_file: dict) -> dict:
    """Build nested tree structure for D3 treemap."""
    root: dict = {"name": "src", "children": {}}

    for f in files:
        parts = f["path"].split("/")
        # Skip leading 'src/' since root is already 'src'
        if parts and parts[0] == "src":
            parts = parts[1:]
        node = root
        for part in parts[:-1]:
            if part not in node["children"]:
                node["children"][part] = {"name": part, "children": {}}
            node = node["children"][part]

        filename = parts[-1]
        resolved = f["abs_path"]
        dep_entry = dep_graph.get(resolved, {"import_count": 0, "importer_count": 0})
        file_findings = findings_by_file.get(f["path"], [])
        open_findings = [ff for ff in file_findings if ff.get("status") == "open"]

        node["children"][filename] = {
            "name": filename,
            "path": f["path"],
            "loc": max(f["loc"], 1),  # D3 needs >0 values
            "fan_in": dep_entry.get("importer_count", 0),
            "fan_out": dep_entry.get("import_count", 0),
            "findings_total": len(file_findings),
            "findings_open": len(open_findings),
            "finding_summaries": [ff.get("summary", "") for ff in open_findings[:20]],
        }

    # Convert children dicts to arrays (D3 format)
    def to_array(node: dict[str, Any]) -> None:
        if "children" in node and isinstance(node["children"], dict):
            children = list(node["children"].values())
            for child in children:
                to_array(child)
            node["children"] = children
            # Remove empty directories
            node["children"] = [
                c
                for c in node["children"]
                if "loc" in c or ("children" in c and c["children"])
            ]

    to_array(root)
    return root


def _build_dep_graph_for_path(path: Path, lang) -> dict:
    """Build dependency graph using the resolved language plugin."""
    resolved_lang = _resolve_visualization_lang(path, lang)
    if resolved_lang and resolved_lang.build_dep_graph:
        return resolved_lang.build_dep_graph(path)
    return {}


def _findings_by_file(state: dict | None) -> dict[str, list]:
    """Group findings from state by file path."""
    result: dict[str, list] = defaultdict(list)
    if state and state.get("findings"):
        for f in state["findings"].values():
            result[f["file"]].append(f)
    return result


def generate_visualization(
    path: Path, state: dict | None = None, output: Path | None = None, lang=None
) -> str:
    """Generate an HTML treemap visualization."""
    files = _collect_file_data(path, lang)
    dep_graph = _build_dep_graph_for_path(path, lang)
    findings_by_file = _findings_by_file(state)
    tree = _build_tree(files, dep_graph, findings_by_file)
    # Escape </ to prevent </script> in filenames from breaking HTML
    tree_json = json.dumps(tree).replace("</", r"<\/")

    # Stats for header
    total_files = len(files)
    total_loc = sum(f["loc"] for f in files)
    total_findings = sum(len(v) for v in findings_by_file.values())
    open_findings = sum(
        1 for fs in findings_by_file.values() for f in fs if f.get("status") == "open"
    )
    if state:
        overall_score = get_overall_score(state)
        objective_score = get_objective_score(state)
        strict_score = get_strict_score(state)
    else:
        overall_score = objective_score = strict_score = None

    def fmt_score(value):
        return f"{value:.1f}" if isinstance(value, int | float) else "N/A"

    replacements = {
        "__D3_CDN_URL__": D3_CDN_URL,
        "__TREE_DATA__": tree_json,
        "__TOTAL_FILES__": str(total_files),
        "__TOTAL_LOC__": f"{total_loc:,}",
        "__TOTAL_FINDINGS__": str(total_findings),
        "__OPEN_FINDINGS__": str(open_findings),
        "__OVERALL_SCORE__": fmt_score(overall_score),
        "__OBJECTIVE_SCORE__": fmt_score(objective_score),
        "__STRICT_SCORE__": fmt_score(strict_score),
    }
    html = _get_html_template()
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)

    if output:
        try:
            safe_write_text(output, html)
        except OSError as e:
            print(f"  \u26a0 Could not write visualization: {e}", file=sys.stderr)
            return html

    return html


def cmd_viz(args: argparse.Namespace) -> None:
    """Generate HTML treemap visualization."""
    path, lang, state = load_cmd_context(args)
    output = Path(getattr(args, "output", None) or ".desloppify/treemap.html")
    print(colorize("Collecting file data and building dependency graph...", "dim"))
    generate_visualization(path, state, output, lang=lang)
    print(colorize(f"\nTreemap written to {output}", "green"))
    print(colorize(f"Open in browser: file://{output.resolve()}", "dim"))

@dataclass
class TreeTextOptions:
    """Text tree rendering options."""
    max_depth: int = 2
    focus: str | None = None
    min_loc: int = 0
    sort_by: str = "loc"
    detail: bool = False


def generate_tree_text(
    path: Path,
    state: dict | None = None,
    options: TreeTextOptions | None = None,
    *,
    lang=None,
) -> str:
    """Generate text-based annotated tree of the codebase."""
    resolved_options = options or TreeTextOptions()
    files = _collect_file_data(path, lang)
    dep_graph = _build_dep_graph_for_path(path, lang)
    tree = _build_tree(files, dep_graph, _findings_by_file(state))

    root = tree
    if resolved_options.focus:
        parts = resolved_options.focus.strip("/").split("/")
        if parts and parts[0] == "src":
            parts = parts[1:]
        for part in parts:
            found = None
            for child in root.get("children", []):
                if child["name"] == part:
                    found = child
                    break
            if found is None:
                return f"Directory not found: {resolved_options.focus}"
            root = found

    lines = render_tree_lines(
        root,
        max_depth=resolved_options.max_depth,
        min_loc=resolved_options.min_loc,
        sort_by=resolved_options.sort_by,
        detail=resolved_options.detail,
    )
    return "\n".join(lines)


def cmd_tree(args: argparse.Namespace) -> None:
    """Print annotated codebase tree to terminal."""
    path, lang, state = load_cmd_context(args)
    print(
        generate_tree_text(
            path,
            state,
            options=TreeTextOptions(
                max_depth=getattr(args, "depth", 2),
                focus=getattr(args, "focus", None),
                min_loc=getattr(args, "min_loc", 0),
                sort_by=getattr(args, "sort", "loc"),
                detail=getattr(args, "detail", False),
            ),
            lang=lang,
        )
    )


def _get_html_template() -> str:
    """Read the HTML treemap template from the external file."""
    return (Path(__file__).parent / "_viz_template.html").read_text()
