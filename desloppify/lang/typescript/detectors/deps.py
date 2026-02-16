"""Dependency graph + coupling analysis (fan-in/fan-out) + dynamic imports."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from ....utils import PROJECT_ROOT, c, grep_files, print_table, rel, resolve_path
from ....detectors.graph import detect_cycles, get_coupling_score, finalize_graph

# Extensions for framework files whose imports should be included in the graph.
# These files can import .ts/.tsx modules but aren't .ts/.tsx themselves.
_FRAMEWORK_EXTENSIONS = (".svelte", ".vue", ".astro")

# Extensions to try when resolving an import specifier to a file on disk.
_RESOLVE_EXTENSIONS = ("", ".ts", ".tsx", "/index.ts", "/index.tsx")

# ── tsconfig paths resolution ──────────────────────────────

_tsconfig_cache: dict[str, dict[str, str]] = {}


def _load_tsconfig_paths(project_root: Path) -> dict[str, str]:
    """Parse tsconfig.json compilerOptions.paths into {prefix: directory}.

    Returns e.g. {"@/": "src/", "@components/": "src/components/"}.
    Falls back to {"@/": "src/"} if no tsconfig found or no paths configured.
    """
    key = str(project_root)
    if key in _tsconfig_cache:
        return _tsconfig_cache[key]

    result = _parse_tsconfig_paths(project_root)
    _tsconfig_cache[key] = result
    return result


def _parse_tsconfig_paths(project_root: Path) -> dict[str, str]:
    """Parse tsconfig paths from disk. Internal — use _load_tsconfig_paths()."""
    fallback = {"@/": "src/"}

    # Try config files in priority order
    for name in ("tsconfig.json", "tsconfig.app.json", "jsconfig.json"):
        config_path = project_root / name
        if config_path.is_file():
            try:
                data = json.loads(config_path.read_text(errors="replace"))
            except (json.JSONDecodeError, OSError):
                continue
            result = _extract_paths(data, project_root)
            if result is not None:
                return result
            # Config exists but no paths — check if it extends another
            extends = data.get("extends")
            if isinstance(extends, str) and not extends.startswith("@"):
                parent_path = (config_path.parent / extends).resolve()
                if parent_path.is_file():
                    try:
                        parent_data = json.loads(parent_path.read_text(errors="replace"))
                    except (json.JSONDecodeError, OSError):
                        return fallback
                    parent_result = _extract_paths(parent_data, parent_path.parent)
                    if parent_result is not None:
                        # Child overrides parent — merge (child wins, but here child has none)
                        return parent_result
            return fallback

    return fallback


def _extract_paths(data: dict, base_dir: Path) -> dict[str, str] | None:
    """Extract paths mapping from a parsed tsconfig. Returns None if no paths field."""
    compiler_options = data.get("compilerOptions")
    if not isinstance(compiler_options, dict):
        return None
    paths = compiler_options.get("paths")
    if not isinstance(paths, dict):
        return None

    base_url = compiler_options.get("baseUrl", ".")
    if not isinstance(base_url, str):
        base_url = "."

    result: dict[str, str] = {}
    for alias, targets in paths.items():
        if not isinstance(targets, list) or not targets:
            continue
        # Use first target (matches TS resolution behavior)
        target = targets[0]
        if not isinstance(target, str):
            continue
        # Strip wildcard: "@/*" → "@/", "./src/*" → "./src/"
        alias_prefix = alias.removesuffix("*")
        target_prefix = target.removesuffix("*")
        # Compose with baseUrl: resolve target relative to baseUrl
        target_dir = target_prefix.removeprefix("./")
        if base_url != ".":
            base = base_url.rstrip("/")
            if target_dir:
                target_dir = base + "/" + target_dir
            else:
                target_dir = base + "/"
        result[alias_prefix] = target_dir

    return result if result else None


# ── Import resolution helpers ──────────────────────────────


def _resolve_alias(module_path: str, tsconfig_paths: dict[str, str],
                   project_root: Path) -> Path | None:
    """Resolve a tsconfig path alias to absolute path, or None if not an alias."""
    for prefix, target_dir in tsconfig_paths.items():
        if module_path.startswith(prefix):
            relative = module_path[len(prefix):]
            return (project_root / target_dir / relative).resolve()
    return None


def _resolve_module(module_path: str, filepath: str,
                    tsconfig_paths: dict[str, str],
                    project_root: Path,
                    graph: dict[str, dict[str, Any]],
                    source_resolved: str) -> None:
    """Resolve an import specifier and add edges to the graph.

    Handles relative imports and tsconfig alias imports. External packages
    (bare specifiers like 'react') are silently ignored.
    """
    target: Path | None = None

    if module_path.startswith("."):
        source_dir = (Path(filepath).parent if Path(filepath).is_absolute()
                      else (project_root / filepath).parent)
        target = (source_dir / module_path).resolve()
    else:
        target = _resolve_alias(module_path, tsconfig_paths, project_root)

    if target is None:
        return  # External package — not in our graph

    for ext in _RESOLVE_EXTENSIONS:
        candidate = Path(str(target) + ext)
        if candidate.is_file():
            target_resolved = str(candidate)
            graph[source_resolved]["imports"].add(target_resolved)
            graph[target_resolved]["importers"].add(source_resolved)
            break


def build_dep_graph(path: Path) -> dict[str, dict[str, Any]]:
    """Build a dependency graph: for each file, who it imports and who imports it.

    Returns {resolved_path: {"imports": set[str], "importers": set[str], "import_count": int, "importer_count": int}}
    """
    from ....utils import find_ts_files, find_source_files

    graph: dict[str, dict[str, Any]] = defaultdict(lambda: {"imports": set(), "importers": set()})
    module_re = re.compile(r"""from\s+['"]([^'"]+)['"]""")
    tsconfig_paths = _load_tsconfig_paths(PROJECT_ROOT)

    # Scan .ts/.tsx files
    ts_files = find_ts_files(path)
    hits = grep_files(r"from\s+['\"]", ts_files)

    for filepath, _lineno, content in hits:
        source_resolved = resolve_path(filepath)
        graph[source_resolved]  # ensure entry exists
        m = module_re.search(content)
        if not m:
            continue
        _resolve_module(m.group(1), filepath, tsconfig_paths, PROJECT_ROOT,
                        graph, source_resolved)

    # Scan framework files (.svelte, .vue, .astro) for imports into .ts/.tsx modules
    fw_files = find_source_files(path, list(_FRAMEWORK_EXTENSIONS))
    if fw_files:
        fw_hits = grep_files(r"from\s+['\"]", fw_files)
        for filepath, _lineno, content in fw_hits:
            source_resolved = resolve_path(filepath)
            graph[source_resolved]  # ensure entry exists
            m = module_re.search(content)
            if not m:
                continue
            _resolve_module(m.group(1), filepath, tsconfig_paths, PROJECT_ROOT,
                            graph, source_resolved)

    return finalize_graph(dict(graph))


def cmd_deps(args: Any) -> None:
    """Show dependency info for a specific file or top coupled files."""
    graph = build_dep_graph(Path(args.path))

    if hasattr(args, "file") and args.file:
        # Single file mode
        coupling = get_coupling_score(args.file, graph)
        if args.json:
            print(json.dumps({"file": rel(args.file), **coupling}, indent=2))
            return
        print(c(f"\nDependency info: {rel(args.file)}\n", "bold"))
        print(f"  Fan-in (importers):  {coupling['fan_in']}")
        print(f"  Fan-out (imports):   {coupling['fan_out']}")
        print(f"  Instability:         {coupling['instability']}")
        if coupling["importers"]:
            print(c(f"\n  Imported by ({coupling['fan_in']}):", "cyan"))
            for p in coupling["importers"][:20]:
                print(f"    {p}")
        if coupling["imports"]:
            print(c(f"\n  Imports ({coupling['fan_out']}):", "cyan"))
            for p in coupling["imports"][:20]:
                print(f"    {p}")
        return

    # Top coupled files mode
    scored = []
    for filepath, entry in graph.items():
        total = entry["import_count"] + entry["importer_count"]
        if total > 5:
            scored.append({
                "file": filepath,
                "fan_in": entry["importer_count"],
                "fan_out": entry["import_count"],
                "total": total,
            })
    scored.sort(key=lambda x: -x["total"])

    if args.json:
        print(json.dumps({"count": len(scored), "entries": [
            {**s, "file": rel(s["file"])} for s in scored[:args.top]
        ]}, indent=2))
        return

    print(c(f"\nMost coupled files: {len(scored)} with >5 connections\n", "bold"))
    rows = []
    for s in scored[:args.top]:
        rows.append([rel(s["file"]), str(s["fan_in"]), str(s["fan_out"]), str(s["total"])])
    print_table(["File", "In", "Out", "Total"], rows, [60, 5, 5, 6])


def cmd_cycles(args: Any) -> None:
    """Show import cycles in the codebase."""
    graph = build_dep_graph(Path(args.path))
    cycles, _ = detect_cycles(graph)

    if args.json:
        print(json.dumps({"count": len(cycles), "cycles": [
            {"length": cy["length"], "files": [rel(f) for f in cy["files"]]}
            for cy in cycles
        ]}, indent=2))
        return

    if not cycles:
        print(c("\nNo import cycles found.", "green"))
        return

    print(c(f"\nImport cycles: {len(cycles)}\n", "bold"))
    for i, cy in enumerate(cycles[:args.top]):
        files = [rel(f) for f in cy["files"]]
        print(c(f"  Cycle {i+1} ({cy['length']} files):", "red" if cy["length"] > 3 else "yellow"))
        for f in files[:8]:
            print(f"    {f}")
        if len(files) > 8:
            print(f"    ... +{len(files) - 8} more")
        print()


def build_dynamic_import_targets(path: Path, extensions: list[str]) -> set[str]:
    """Find files referenced by dynamic imports (import('...')) and side-effect imports."""
    from ....utils import find_source_files
    targets: set[str] = set()
    # Also scan framework files for dynamic imports
    all_extensions = extensions + [e for e in _FRAMEWORK_EXTENSIONS
                                   if e not in extensions]
    files = find_source_files(path, all_extensions)

    hits = grep_files(r"import\s*\(\s*['\"]", files)
    module_re = re.compile(r"""import\s*\(\s*['"]([^'"]+)['"]""")
    for _fp, _ln, content in hits:
        m = module_re.search(content)
        if m:
            targets.add(m.group(1))

    hits2 = grep_files(r"^import\s+['\"]", files)
    side_re = re.compile(r"""import\s+['"]([^'"]+)['"]""")
    for _fp, _ln, content in hits2:
        m = side_re.search(content)
        if m:
            targets.add(m.group(1))

    return targets


def ts_alias_resolver(target: str) -> str:
    """Resolve TS path aliases using tsconfig.json paths."""
    paths = _load_tsconfig_paths(PROJECT_ROOT)
    for prefix, target_dir in paths.items():
        if target.startswith(prefix):
            return target_dir + target[len(prefix):]
    return target
