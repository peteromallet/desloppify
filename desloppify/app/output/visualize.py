"""Codebase treemap visualization with HTML output and LLM-readable tree text."""

import json
from importlib import resources
from dataclasses import dataclass
from pathlib import Path

from desloppify.app.output.visualize_data import (
    _build_dep_graph_for_path,
    _build_tree,
    _collect_file_data,
    _issues_by_file,
)
from desloppify.app.output.tree_text import render_tree_lines
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.output.contract import OutputResult
from desloppify.base.output.fallbacks import print_write_error
from desloppify.state_scoring import score_snapshot

D3_CDN_URL = "https://d3js.org/d3.v7.min.js"


__all__ = [
    "D3_CDN_URL",
    "TreeTextOptions",
    "generate_tree_text",
    "generate_visualization",
]


def _write_visualization_output(output: Path, html: str) -> OutputResult:
    """Write visualization HTML to disk using the shared output-result contract."""
    try:
        safe_write_text(output, html)
    except OSError as exc:
        return OutputResult(
            ok=False,
            status="error",
            message=str(exc),
            error_kind="visualization_write_error",
        )
    return OutputResult(ok=True, status="written", message=f"wrote {output}")


def generate_visualization(
    path: Path, state: dict | None = None, output: Path | None = None, lang=None
) -> tuple[str, OutputResult]:
    """Generate an HTML treemap visualization and explicit output result."""
    try:
        files = _collect_file_data(path, lang)
        dep_graph = _build_dep_graph_for_path(path, lang)
        issues_by_file = _issues_by_file(state)
        tree = _build_tree(files, dep_graph, issues_by_file)
        # Escape </ to prevent </script> in filenames from breaking HTML
        tree_json = json.dumps(tree).replace("</", r"<\/")

        # Stats for header
        total_files = len(files)
        total_loc = sum(f["loc"] for f in files)
        total_issues = sum(len(v) for v in issues_by_file.values())
        open_issues = sum(
            1 for fs in issues_by_file.values() for f in fs if f.get("status") == "open"
        )
        if state:
            scores = score_snapshot(state)
            overall_score = scores.overall
            objective_score = scores.objective
            strict_score = scores.strict
        else:
            overall_score = objective_score = strict_score = None

        def _fmt_viz_score(value):
            return f"{value:.1f}" if isinstance(value, int | float) else "N/A"

        replacements = {
            "__D3_CDN_URL__": D3_CDN_URL,
            "__TREE_DATA__": tree_json,
            "__TOTAL_FILES__": str(total_files),
            "__TOTAL_LOC__": f"{total_loc:,}",
            "__TOTAL_ISSUES__": str(total_issues),
            "__OPEN_ISSUES__": str(open_issues),
            "__OVERALL_SCORE__": _fmt_viz_score(overall_score),
            "__OBJECTIVE_SCORE__": _fmt_viz_score(objective_score),
            "__STRICT_SCORE__": _fmt_viz_score(strict_score),
        }
        html = _get_html_template()
        for placeholder, value in replacements.items():
            html = html.replace(placeholder, value)
    except OSError as exc:
        return "", OutputResult(
            ok=False,
            status="error",
            message=str(exc),
            error_kind="visualization_generation_error",
        )

    if output:
        write_result = _write_visualization_output(output, html)
        if not write_result.ok:
            message = write_result.message or "unknown write failure"
            print_write_error(output, OSError(message), label="visualization")
            return html, write_result
        return html, write_result

    return html, OutputResult(
        ok=True,
        status="not_requested",
        message="visualization generated in memory only",
    )


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
    tree = _build_tree(files, dep_graph, _issues_by_file(state))

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


def _get_html_template() -> str:
    """Read the HTML treemap template from the external file."""
    return (
        resources.files("desloppify.app.output")
        .joinpath("_viz_template.html")
        .read_text()
    )
