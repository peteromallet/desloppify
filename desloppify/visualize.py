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
import subprocess
from collections import defaultdict
from pathlib import Path

from .utils import PROJECT_ROOT, c, rel


def _collect_file_data(path: Path) -> list[dict]:
    """Collect LOC for all TS/TSX files."""
    result = subprocess.run(
        ["find", str(path), "-name", "*.ts", "-o", "-name", "*.tsx"],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    files = []
    for filepath in result.stdout.strip().splitlines():
        if not filepath or "node_modules" in filepath:
            continue
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


def generate_visualization(path: Path, state: dict | None = None,
                           output: Path | None = None) -> str:
    """Generate an HTML treemap visualization."""
    from .lang.typescript.deps import build_dep_graph

    # Collect data
    files = _collect_file_data(path)
    dep_graph = build_dep_graph(path)

    # Get findings from state if available
    findings_by_file: dict[str, list] = defaultdict(list)
    if state and state.get("findings"):
        for f in state["findings"].values():
            findings_by_file[f["file"]].append(f)

    tree = _build_tree(files, dep_graph, findings_by_file)
    tree_json = json.dumps(tree)

    # Stats for header
    total_files = len(files)
    total_loc = sum(f["loc"] for f in files)
    total_findings = sum(len(v) for v in findings_by_file.values())
    open_findings = sum(1 for fs in findings_by_file.values()
                        for f in fs if f.get("status") == "open")
    score = state.get("score", "N/A") if state else "N/A"

    html = _HTML_TEMPLATE.replace("__D3_CDN_URL__", D3_CDN_URL)
    html = html.replace("__TREE_DATA__", tree_json)
    html = html.replace("__TOTAL_FILES__", str(total_files))
    html = html.replace("__TOTAL_LOC__", f"{total_loc:,}")
    html = html.replace("__TOTAL_FINDINGS__", str(total_findings))
    html = html.replace("__OPEN_FINDINGS__", str(open_findings))
    html = html.replace("__SCORE__", str(score))

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(html)

    return html


def cmd_viz(args):
    """Generate HTML treemap visualization."""
    from .state import load_state

    path = Path(args.path)
    state = None
    state_path = getattr(args, "state", None)
    try:
        state = load_state(Path(state_path) if state_path else None)
    except (OSError, json.JSONDecodeError):
        pass

    output = Path(getattr(args, "output", None) or ".desloppify/treemap.html")
    print(c("Collecting file data and building dependency graph...", "dim"))
    generate_visualization(path, state, output)
    print(c(f"\nTreemap written to {output}", "green"))
    print(c(f"Open in browser: file://{output.resolve()}", "dim"))


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
                       detail: bool = False) -> str:
    """Generate text-based annotated tree of the codebase.

    Args:
        path: Directory to scan.
        state: Desloppify state (for findings overlay).
        max_depth: How many levels deep to show.
        focus: Focus on a subdirectory (e.g. 'shared/components/MediaLightbox').
        min_loc: Hide files/dirs below this LOC threshold.
        sort_by: 'loc', 'findings', or 'coupling'.
        detail: Show finding summaries under each file.
    """
    from .lang.typescript.deps import build_dep_graph

    files = _collect_file_data(path)
    dep_graph = build_dep_graph(path)

    findings_by_file: dict[str, list] = defaultdict(list)
    if state and state.get("findings"):
        for f in state["findings"].values():
            findings_by_file[f["file"]].append(f)

    tree = _build_tree(files, dep_graph, findings_by_file)

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
    from .state import load_state

    path = Path(args.path)
    state = None
    try:
        state = load_state(Path(args.state) if getattr(args, "state", None) else None)
    except (OSError, json.JSONDecodeError):
        pass

    max_depth = getattr(args, "depth", 2)
    focus = getattr(args, "focus", None)
    min_loc = getattr(args, "min_loc", 0)
    sort_by = getattr(args, "sort", "loc")
    detail = getattr(args, "detail", False)

    print(generate_tree_text(path, state, max_depth=max_depth, focus=focus,
                             min_loc=min_loc, sort_by=sort_by, detail=detail))


# ── HTML Template ────────────────────────────────────────────

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Desloppify — Codebase Treemap</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
         background: #0d1117; color: #c9d1d9; overflow: hidden; }

  #header { padding: 12px 20px; background: #161b22; border-bottom: 1px solid #30363d;
            display: flex; align-items: center; gap: 24px; flex-wrap: wrap; }
  #header h1 { font-size: 16px; font-weight: 600; color: #f0f6fc; white-space: nowrap; }
  .stat { font-size: 13px; color: #8b949e; }
  .stat strong { color: #c9d1d9; font-variant-numeric: tabular-nums; }
  .stat.score strong { color: #58a6ff; font-size: 15px; }

  #controls { margin-left: auto; display: flex; gap: 8px; align-items: center; }
  #controls label { font-size: 12px; color: #8b949e; }
  #controls select { background: #21262d; border: 1px solid #30363d; color: #c9d1d9;
                     padding: 4px 8px; border-radius: 4px; font-size: 12px; }

  #breadcrumb { padding: 8px 20px; background: #161b22; border-bottom: 1px solid #30363d;
                font-size: 13px; color: #8b949e; }
  #breadcrumb span { color: #58a6ff; cursor: pointer; }
  #breadcrumb span:hover { text-decoration: underline; }

  #chart { width: 100vw; height: calc(100vh - 85px); }

  #tooltip { position: fixed; pointer-events: none; background: #1c2128; border: 1px solid #30363d;
             border-radius: 6px; padding: 10px 14px; font-size: 12px; line-height: 1.5;
             max-width: 400px; z-index: 100; box-shadow: 0 4px 12px rgba(0,0,0,0.4);
             display: none; }
  .tt-path { color: #58a6ff; font-weight: 600; font-size: 13px;
             word-break: break-all; margin-bottom: 4px; }
  .tt-stats { color: #8b949e; }
  .tt-stats strong { color: #c9d1d9; }
  .tt-findings { margin-top: 6px; border-top: 1px solid #30363d; padding-top: 6px; }
  .tt-finding { color: #f0883e; font-size: 11px; }
</style>
</head>
<body>
<div id="header">
  <h1>Desloppify Treemap</h1>
  <span class="stat">Files: <strong>__TOTAL_FILES__</strong></span>
  <span class="stat">LOC: <strong>__TOTAL_LOC__</strong></span>
  <span class="stat">Findings: <strong>__OPEN_FINDINGS__</strong> open / __TOTAL_FINDINGS__ total</span>
  <span class="stat score">Score: <strong>__SCORE__/100</strong></span>
  <div id="controls">
    <label>Color by:</label>
    <select id="colorMode">
      <option value="findings">Cruft (findings)</option>
      <option value="coupling">Coupling (fan-in + fan-out)</option>
      <option value="loc">File size (LOC)</option>
    </select>
  </div>
</div>
<div id="breadcrumb"><span data-depth="0">src</span></div>
<div id="chart"></div>
<div id="tooltip"></div>

<script src="__D3_CDN_URL__"></script>
<script>
const data = __TREE_DATA__;
const chartEl = document.getElementById('chart');
const tooltip = document.getElementById('tooltip');
const breadcrumbEl = document.getElementById('breadcrumb');
const colorSelect = document.getElementById('colorMode');

// Color scales
const cruftScale = d3.scaleSequential(d3.interpolateRdYlGn).domain([10, 0]);
const couplingScale = d3.scaleSequential(d3.interpolateYlOrRd).domain([0, 40]);
const locScale = d3.scaleSequential(d3.interpolateBlues).domain([0, 800]);

let colorMode = 'findings';

function getColor(d) {
  if (!d.data.loc) return '#21262d';
  const dd = d.data;
  if (colorMode === 'findings') return cruftScale(Math.min(dd.findings_open || 0, 10));
  if (colorMode === 'coupling') return couplingScale(Math.min((dd.fan_in||0) + (dd.fan_out||0), 40));
  if (colorMode === 'loc') return locScale(Math.min(dd.loc||0, 800));
  return '#21262d';
}

function isLightBg(color) {
  const c = d3.color(color);
  return c ? (c.r * 0.299 + c.g * 0.587 + c.b * 0.114) > 140 : false;
}

// Build D3 hierarchy
const root = d3.hierarchy(data)
  .sum(d => d.loc || 0)
  .sort((a, b) => (b.value || 0) - (a.value || 0));

let currentFocus = root;

const svg = d3.select('#chart').append('svg');

function getSize() {
  return [chartEl.clientWidth, chartEl.clientHeight];
}

function render(focus) {
  currentFocus = focus;
  const [W, H] = getSize();
  svg.attr('width', W).attr('height', H);

  // Layout this subtree
  d3.treemap()
    .size([W, H])
    .paddingTop(d => d === focus ? 0 : 18)
    .paddingRight(2).paddingBottom(2).paddingLeft(2)
    .paddingInner(1)
    .round(true)(focus);

  svg.selectAll('*').remove();

  // Breadcrumb
  const ancestors = focus.ancestors().reverse();
  breadcrumbEl.innerHTML = ancestors.map((a, i) =>
    i < ancestors.length - 1
      ? `<span data-depth="${i}">${a.data.name}</span>`
      : `<strong>${a.data.name}</strong>`
  ).join(' / ');

  if (!focus.children) return;

  // Render each immediate child
  focus.children.forEach(child => {
    if (child.children) {
      renderDir(child);
    } else {
      renderLeaf(svg, child);
    }
  });
}

function renderDir(dir) {
  const w = dir.x1 - dir.x0;
  const h = dir.y1 - dir.y0;
  if (w < 3 || h < 3) return;

  const g = svg.append('g');

  // Directory background
  g.append('rect')
    .attr('x', dir.x0).attr('y', dir.y0)
    .attr('width', w).attr('height', h)
    .attr('fill', '#161b22')
    .attr('stroke', '#30363d').attr('stroke-width', 0.5)
    .attr('rx', 2)
    .style('cursor', 'pointer')
    .on('click', () => render(dir))
    .on('mouseenter', e => showDirTooltip(e, dir))
    .on('mousemove', moveTooltip)
    .on('mouseleave', hideTooltip);

  // Directory label
  if (w > 30) {
    const maxChars = Math.floor((w - 8) / 7);
    const label = dir.data.name.length > maxChars
      ? dir.data.name.slice(0, maxChars - 1) + '…'
      : dir.data.name;
    g.append('text')
      .attr('x', dir.x0 + 4).attr('y', dir.y0 + 13)
      .attr('fill', '#8b949e').attr('font-size', '11px').attr('font-weight', 500)
      .style('pointer-events', 'none')
      .text(label + '/');
  }

  // Render all leaf descendants
  const leaves = dir.descendants().filter(d => !d.children);
  leaves.forEach(leaf => renderLeaf(g, leaf));
}

function renderLeaf(parent, d) {
  const w = d.x1 - d.x0;
  const h = d.y1 - d.y0;
  if (w < 2 || h < 2) return;

  const color = getColor(d);
  parent.append('rect')
    .attr('x', d.x0).attr('y', d.y0)
    .attr('width', w).attr('height', h)
    .attr('fill', color)
    .attr('stroke', '#0d1117').attr('stroke-width', 0.5)
    .attr('rx', 1)
    .style('cursor', 'pointer')
    .on('click', e => { e.stopPropagation(); })
    .on('mouseenter', e => showFileTooltip(e, d))
    .on('mousemove', moveTooltip)
    .on('mouseleave', hideTooltip);

  // File name label
  if (w > 30 && h > 14) {
    const name = d.data.name.replace(/\.(tsx?|jsx?)$/, '');
    const maxChars = Math.floor((w - 6) / 6);
    const label = name.length > maxChars ? name.slice(0, maxChars - 1) + '…' : name;
    parent.append('text')
      .attr('x', d.x0 + 3).attr('y', d.y0 + 11)
      .attr('fill', isLightBg(color) ? '#0d1117' : '#e6edf3')
      .attr('font-size', '10px').attr('font-weight', 600)
      .style('pointer-events', 'none')
      .text(label);
  }
}

// Tooltips
function showFileTooltip(event, d) {
  const dd = d.data;
  let html = `<div class="tt-path">${dd.path || dd.name}</div><div class="tt-stats">`;
  html += `<strong>${(dd.loc||0).toLocaleString()}</strong> LOC`;
  html += ` · Fan-in: <strong>${dd.fan_in||0}</strong> · Fan-out: <strong>${dd.fan_out||0}</strong>`;
  if (dd.findings_open > 0)
    html += ` · <strong style="color:#f0883e">${dd.findings_open} findings</strong>`;
  html += `</div>`;
  if (dd.finding_summaries && dd.finding_summaries.length) {
    html += `<div class="tt-findings">`;
    dd.finding_summaries.slice(0,5).forEach(s => { html += `<div class="tt-finding">• ${s}</div>`; });
    if (dd.finding_summaries.length > 5)
      html += `<div class="tt-finding">… +${dd.finding_summaries.length-5} more</div>`;
    html += `</div>`;
  }
  tooltip.innerHTML = html;
  tooltip.style.display = 'block';
  moveTooltip(event);
}

function showDirTooltip(event, d) {
  const leaves = d.leaves();
  const loc = d3.sum(leaves, l => l.data.loc || 0);
  const findings = d3.sum(leaves, l => l.data.findings_open || 0);
  const path = d.ancestors().reverse().map(a => a.data.name).join('/');
  let html = `<div class="tt-path">${path}/</div><div class="tt-stats">`;
  html += `<strong>${leaves.length}</strong> files · <strong>${loc.toLocaleString()}</strong> LOC`;
  if (findings > 0) html += ` · <strong style="color:#f0883e">${findings} findings</strong>`;
  html += `</div>`;
  tooltip.innerHTML = html;
  tooltip.style.display = 'block';
  moveTooltip(event);
}

function moveTooltip(e) {
  let x = e.clientX + 12, y = e.clientY + 12;
  if (x + 380 > window.innerWidth) x = e.clientX - 380;
  if (y + 180 > window.innerHeight) y = e.clientY - 180;
  tooltip.style.left = x + 'px';
  tooltip.style.top = y + 'px';
}

function hideTooltip() { tooltip.style.display = 'none'; }

// Breadcrumb click → navigate up
breadcrumbEl.addEventListener('click', e => {
  const span = e.target.closest('span[data-depth]');
  if (!span) return;
  const depth = parseInt(span.dataset.depth);
  const ancestors = currentFocus.ancestors().reverse();
  if (depth < ancestors.length) render(ancestors[depth]);
});

// Color mode
colorSelect.addEventListener('change', () => { colorMode = colorSelect.value; render(currentFocus); });

// Resize
window.addEventListener('resize', () => render(currentFocus));

// Go
render(root);
</script>
</body>
</html>"""
