"""Dependency graph + coupling analysis (fan-in/fan-out) + dynamic imports."""

import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from ....utils import PROJECT_ROOT, SRC_PATH, c, print_table, rel, resolve_path
from ....detectors.graph import detect_cycles, get_coupling_score, finalize_graph


def build_dep_graph(path: Path) -> dict[str, dict]:
    """Build a dependency graph: for each file, who it imports and who imports it.

    Returns {resolved_path: {"imports": set[str], "importers": set[str], "import_count": int, "importer_count": int}}
    """
    # Single grep pass for all import/from lines
    result = subprocess.run(
        ["grep", "-rn", "--include=*.ts", "--include=*.tsx", "-E",
         r"from\s+['\"]", str(path)],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )

    graph: dict[str, dict] = defaultdict(lambda: {"imports": set(), "importers": set()})
    module_re = re.compile(r"""from\s+['"]([^'"]+)['"]""")

    for line in result.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        filepath, content = parts[0], parts[2]
        source_resolved = resolve_path(filepath)
        graph[source_resolved]  # ensure entry exists

        m = module_re.search(content)
        if not m:
            continue
        module_path = m.group(1)
        # Resolve relative imports to absolute paths
        if module_path.startswith("."):
            source_dir = Path(filepath).parent if Path(filepath).is_absolute() else (PROJECT_ROOT / filepath).parent
            target = (source_dir / module_path).resolve()
            # Try common extensions (is_file() excludes directories)
            for ext in ["", ".ts", ".tsx", "/index.ts", "/index.tsx"]:
                candidate = Path(str(target) + ext)
                if candidate.is_file():
                    target_resolved = str(candidate)
                    graph[source_resolved]["imports"].add(target_resolved)
                    graph[target_resolved]["importers"].add(source_resolved)
                    break
        elif module_path.startswith("@/"):
            # Alias: @/ -> src/
            relative = module_path[2:]
            target = SRC_PATH / relative
            for ext in ["", ".ts", ".tsx", "/index.ts", "/index.tsx"]:
                candidate = Path(str(target) + ext)
                if candidate.is_file():
                    target_resolved = str(candidate)
                    graph[source_resolved]["imports"].add(target_resolved)
                    graph[target_resolved]["importers"].add(source_resolved)
                    break

    return finalize_graph(dict(graph))


def cmd_deps(args):
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


def cmd_cycles(args):
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
    targets: set[str] = set()
    include_args = [arg for ext in extensions for arg in (f"--include=*{ext}",)]

    result = subprocess.run(
        ["grep", "-rn", *include_args, "-E",
         r"import\s*\(\s*['\"]", str(path)],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    module_re = re.compile(r"""import\s*\(\s*['"]([^'"]+)['"]""")
    for line in result.stdout.splitlines():
        m = module_re.search(line)
        if m:
            targets.add(m.group(1))

    result2 = subprocess.run(
        ["grep", "-rn", *include_args, "-E",
         r"^import\s+['\"]", str(path)],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    side_re = re.compile(r"""import\s+['"]([^'"]+)['"]""")
    for line in result2.stdout.splitlines():
        m = side_re.search(line)
        if m:
            targets.add(m.group(1))

    return targets


def ts_alias_resolver(target: str) -> str:
    """Resolve TS/Vite @/ alias to src/."""
    return target.replace("@/", "src/") if target.startswith("@/") else target
