"""Codebase treemap visualization — self-contained HTML with D3.js.

Generates an interactive treemap where:
- Rectangles = files, sized by LOC
- Color = cruft density (green → yellow → red)
- Click to zoom into directories, click header to zoom out
- Hover tooltip shows: LOC, fan-in/fan-out, open findings, file path
- Toggle color mode: cruft score, coupling, LOC
"""

D3_CDN_URL = "https://d3js.org/d3.v7.min.js"

import json
from collections import defaultdict
from pathlib import Path

from ..utils import PROJECT_ROOT, colorize, rel


def _collect_file_data(path: Path, lang=None) -> list[dict]:
    """Collect LOC for all source files using the language's file finder."""
    if lang and lang.file_finder:
        source_files = lang.file_finder(path)
    else:
        from ..utils import find_source_files
        source_files = find_source_files(path, [".ts", ".tsx", ".py", ".cs"])
    files = []
    for filepath in source_files:
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
            content = p.read_text()
            loc = len(content.splitlines())
            files.append({
                "path": rel(filepath),
                "abs_path": str(p.resolve()),
                "loc": loc,
            })
        except (OSError, UnicodeDecodeError):
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
    def to_array(node):
        if "children" in node and isinstance(node["children"], dict):
            children = list(node["children"].values())
            for child in children:
                to_array(child)
            node["children"] = children
            # Remove empty directories
            node["children"] = [c for c in node["children"]
                                if "loc" in c or ("children" in c and c["children"])]
    to_array(root)
    return root


def _build_dep_graph_for_path(path: Path, lang) -> dict:
    """Build dependency graph using lang plugin or fallback to TS."""
    if lang and lang.build_dep_graph:
        return lang.build_dep_graph(path)
    if not lang:
        try:
            from ..lang.typescript.deps import build_dep_graph
            return build_dep_graph(path)
        except (ImportError, ModuleNotFoundError):
            pass
    return {}


def _findings_by_file(state: dict | None) -> dict[str, list]:
    """Group findings from state by file path."""
    result: dict[str, list] = defaultdict(list)
    if state and state.get("findings"):
        for f in state["findings"].values():
            result[f["file"]].append(f)
    return result


def generate_visualization(path: Path, state: dict | None = None,
                           output: Path | None = None, lang=None) -> str:
    """Generate an HTML treemap visualization."""
    files = _collect_file_data(path, lang)
    dep_graph = _build_dep_graph_for_path(path, lang)
    fbf = _findings_by_file(state)
    tree = _build_tree(files, dep_graph, fbf)
    # Escape </ to prevent </script> in filenames from breaking HTML
    tree_json = json.dumps(tree).replace("</", r"<\/")

    # Stats for header
    total_files = len(files)
    total_loc = sum(f["loc"] for f in files)
    total_findings = sum(len(v) for v in fbf.values())
    open_findings = sum(1 for fs in fbf.values()
                        for f in fs if f.get("status") == "open")
    score = state.get("score", "N/A") if state else "N/A"

    replacements = {"__D3_CDN_URL__": D3_CDN_URL, "__TREE_DATA__": tree_json,
                     "__TOTAL_FILES__": str(total_files), "__TOTAL_LOC__": f"{total_loc:,}",
                     "__TOTAL_FINDINGS__": str(total_findings),
                     "__OPEN_FINDINGS__": str(open_findings), "__SCORE__": str(score)}
    html = _get_html_template()
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)

    if output:
        try:
            from ..utils import safe_write_text
            safe_write_text(output, html)
        except OSError as e:
            import sys
            print(f"  \u26a0 Could not write visualization: {e}", file=sys.stderr)

    return html


def _load_cmd_context(args):
    """Load lang config and state from CLI args."""
    from ..state import load_state
    from ..commands._helpers import resolve_lang
    lang = resolve_lang(args)
    state = None
    try:
        state = load_state(Path(args.state) if getattr(args, "state", None) else None)
    except (OSError, json.JSONDecodeError):
        pass
    return Path(args.path), lang, state


def cmd_viz(args):
    """Generate HTML treemap visualization."""
    path, lang, state = _load_cmd_context(args)
    output = Path(getattr(args, "output", None) or ".desloppify/treemap.html")
    print(colorize("Collecting file data and building dependency graph...", "dim"))
    generate_visualization(path, state, output, lang=lang)
    print(colorize(f"\nTreemap written to {output}", "green"))
    print(colorize(f"Open in browser: file://{output.resolve()}", "dim"))


# ── Text tree (LLM-readable) ────────────────────────────────

def _aggregate(node: dict) -> dict:
    """Compute aggregate stats for a tree node."""
    if "children" not in node:
        return {
            "files": 1,
            "loc": node.get("loc", 0),
            "findings": node.get("findings_open", 0),
            "max_coupling": node.get("fan_in", 0) + node.get("fan_out", 0),
        }
    agg = {"files": 0, "loc": 0, "findings": 0, "max_coupling": 0}
    for child in node["children"]:
        child_agg = _aggregate(child)
        agg["files"] += child_agg["files"]
        agg["loc"] += child_agg["loc"]
        agg["findings"] += child_agg["findings"]
        agg["max_coupling"] = max(agg["max_coupling"], child_agg["max_coupling"])
    return agg


def _print_tree(node: dict, indent: int, max_depth: int, min_loc: int,
                sort_by: str, detail: bool, lines: list[str]):
    """Recursively print annotated tree."""
    prefix = "  " * indent

    if "children" not in node:
        # Leaf file
        loc = node.get("loc", 0)
        if loc < min_loc:
            return
        findings = node.get("findings_open", 0)
        coupling = node.get("fan_in", 0) + node.get("fan_out", 0)
        parts = []
        parts.append(f"{loc:,} LOC")
        if findings > 0:
            parts.append(f"⚠{findings}")
        if coupling > 10:
            parts.append(f"c:{coupling}")
        lines.append(f"{prefix}{node['name']}  ({', '.join(parts)})")

        # Detail: show finding summaries under the file
        if detail and node.get("finding_summaries"):
            for s in node["finding_summaries"]:
                lines.append(f"{prefix}  → {s}")
        return

    # Directory
    agg = _aggregate(node)
    if agg["loc"] < min_loc:
        return

    lines.append(f"{prefix}{node['name']}/  ({agg['files']} files, {agg['loc']:,} LOC, {agg['findings']} findings)")

    if indent >= max_depth:
        return

    # Sort children
    children = node["children"]
    if sort_by == "findings":
        children = sorted(children, key=lambda c: -_aggregate(c)["findings"])
    elif sort_by == "coupling":
        children = sorted(children, key=lambda c: -_aggregate(c)["max_coupling"])
    else:  # loc (default)
        children = sorted(children, key=lambda c: -_aggregate(c)["loc"])

    for child in children:
        _print_tree(child, indent + 1, max_depth, min_loc, sort_by, detail, lines)


def generate_tree_text(path: Path, state: dict | None = None, *,
                       max_depth: int = 2, focus: str | None = None,
                       min_loc: int = 0, sort_by: str = "loc",
                       detail: bool = False, lang=None) -> str:
    """Generate text-based annotated tree of the codebase.

    Args:
        path: Directory to scan.
        state: Desloppify state (for findings overlay).
        max_depth: How many levels deep to show.
        focus: Focus on a subdirectory (e.g. 'shared/components/MediaLightbox').
        min_loc: Hide files/dirs below this LOC threshold.
        sort_by: 'loc', 'findings', or 'coupling'.
        detail: Show finding summaries under each file.
        lang: Language config for file discovery and dep graph.
    """
    files = _collect_file_data(path, lang)
    dep_graph = _build_dep_graph_for_path(path, lang)
    tree = _build_tree(files, dep_graph, _findings_by_file(state))

    # Navigate to focus if specified
    root = tree
    if focus:
        parts = focus.strip("/").split("/")
        # Strip leading 'src' if present (root is already 'src')
        if parts and parts[0] == "src":
            parts = parts[1:]
        for part in parts:
            found = None
            for child in root.get("children", []):
                if child["name"] == part:
                    found = child
                    break
            if found is None:
                return f"Directory not found: {focus}"
            root = found

    lines: list[str] = []
    _print_tree(root, 0, max_depth, min_loc, sort_by, detail, lines)
    return "\n".join(lines)


def cmd_tree(args):
    """Print annotated codebase tree to terminal."""
    path, lang, state = _load_cmd_context(args)
    print(generate_tree_text(
        path, state, max_depth=getattr(args, "depth", 2),
        focus=getattr(args, "focus", None), min_loc=getattr(args, "min_loc", 0),
        sort_by=getattr(args, "sort", "loc"), detail=getattr(args, "detail", False),
        lang=lang))


def _get_html_template() -> str:
    """Read the HTML treemap template from the external file."""
    return (Path(__file__).parent / "_viz_template.html").read_text()
