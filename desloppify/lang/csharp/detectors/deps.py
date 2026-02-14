"""C# dependency graph builder + coupling display commands."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from ....detectors.graph import detect_cycles, finalize_graph, get_coupling_score
from ....utils import PROJECT_ROOT, c, print_table, rel, resolve_path
from ..extractors import CSHARP_FILE_EXCLUSIONS, find_csharp_files

_USING_RE = re.compile(r"(?m)^\s*(?:global\s+)?using\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;")
_USING_ALIAS_RE = re.compile(
    r"(?m)^\s*(?:global\s+)?using\s+[A-Za-z_]\w*\s*=\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;"
)
_USING_STATIC_RE = re.compile(
    r"(?m)^\s*(?:global\s+)?using\s+static\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;"
)
_NAMESPACE_RE = re.compile(
    r"(?m)^\s*namespace\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*(?:;|\{)"
)

_PROJECT_EXCLUSIONS = set(CSHARP_FILE_EXCLUSIONS) | {".git"}


def _is_excluded_path(path: Path) -> bool:
    """True when path is under a known excluded directory."""
    return any(part in _PROJECT_EXCLUSIONS for part in path.parts)


def _find_csproj_files(path: Path) -> list[Path]:
    """Find .csproj files under path, excluding build artifact directories."""
    found: list[Path] = []
    for p in path.rglob("*.csproj"):
        if _is_excluded_path(p):
            continue
        found.append(p.resolve())
    return sorted(found)


def _parse_csproj_references(csproj_file: Path) -> tuple[set[Path], str | None]:
    """Parse ProjectReference includes and optional RootNamespace."""
    refs: set[Path] = set()
    root_ns: str | None = None
    try:
        root = ET.parse(csproj_file).getroot()
    except (ET.ParseError, OSError):
        return refs, root_ns

    for elem in root.iter():
        tag = elem.tag.split("}", 1)[-1]
        if tag == "ProjectReference":
            include = elem.attrib.get("Include")
            if include:
                refs.add((csproj_file.parent / include).resolve())
        elif tag == "RootNamespace":
            if elem.text and elem.text.strip():
                root_ns = elem.text.strip()
    return refs, root_ns


def _map_file_to_project(cs_files: list[str], projects: list[Path]) -> dict[str, Path]:
    """Assign each source file to the nearest containing .csproj directory."""
    project_dirs = sorted((p.parent for p in projects), key=lambda d: len(d.parts), reverse=True)
    mapping: dict[str, Path] = {}
    for filepath in cs_files:
        abs_file = Path(resolve_path(filepath))
        for proj_dir in project_dirs:
            try:
                abs_file.relative_to(proj_dir)
            except ValueError:
                continue
            # Choose the .csproj file in that directory.
            match = next((p for p in projects if p.parent == proj_dir), None)
            if match is not None:
                mapping[str(abs_file)] = match
                break
    return mapping


def _parse_file_metadata(filepath: str) -> tuple[str | None, set[str]]:
    """Return (namespace, using_namespaces) for one C# file."""
    abs_path = Path(resolve_path(filepath))
    try:
        content = abs_path.read_text()
    except (OSError, UnicodeDecodeError):
        return None, set()

    namespace = None
    ns_match = _NAMESPACE_RE.search(content)
    if ns_match:
        namespace = ns_match.group(1)

    usings: set[str] = set()
    usings.update(_USING_RE.findall(content))
    usings.update(_USING_ALIAS_RE.findall(content))
    usings.update(_USING_STATIC_RE.findall(content))
    return namespace, usings


def _expand_namespace_matches(using_ns: str, namespace_to_files: dict[str, set[str]]) -> set[str]:
    """Resolve one using namespace to candidate target files."""
    out: set[str] = set()
    for ns, files in namespace_to_files.items():
        if ns == using_ns or ns.startswith(using_ns + ".") or using_ns.startswith(ns + "."):
            out.update(files)
    return out


def build_dep_graph(path: Path) -> dict[str, dict]:
    """Build a C# dependency graph compatible with shared graph detectors."""
    graph: dict[str, dict] = defaultdict(lambda: {"imports": set(), "importers": set()})

    cs_files = find_csharp_files(path)
    if not cs_files:
        return finalize_graph({})

    projects = _find_csproj_files(path)
    project_refs: dict[Path, set[Path]] = {}
    project_root_ns: dict[Path, str | None] = {}
    for p in projects:
        refs, root_ns = _parse_csproj_references(p)
        project_refs[p] = refs
        project_root_ns[p] = root_ns

    file_to_project = _map_file_to_project(cs_files, projects)

    namespace_to_files: dict[str, set[str]] = defaultdict(set)
    file_to_namespace: dict[str, str | None] = {}
    file_to_usings: dict[str, set[str]] = {}
    for filepath in cs_files:
        source = resolve_path(filepath)
        namespace, usings = _parse_file_metadata(filepath)
        file_to_namespace[source] = namespace
        file_to_usings[source] = usings
        graph[source]
        if namespace:
            namespace_to_files[namespace].add(source)

    # Add project root namespaces as fallback namespace owners.
    for source, proj in file_to_project.items():
        ns = project_root_ns.get(proj)
        if ns and source not in namespace_to_files[ns]:
            namespace_to_files[ns].add(source)

    project_to_namespaces: dict[Path, set[str]] = defaultdict(set)
    for source, ns in file_to_namespace.items():
        if not ns:
            continue
        proj = file_to_project.get(source)
        if proj is not None:
            project_to_namespaces[proj].add(ns)

    for source, usings in file_to_usings.items():
        proj = file_to_project.get(source)
        allowed_namespaces: set[str] | None = None
        if proj is not None:
            allowed_projects = {proj} | project_refs.get(proj, set())
            allowed_namespaces = set()
            for ap in allowed_projects:
                allowed_namespaces.update(project_to_namespaces.get(ap, set()))

        for using_ns in usings:
            for target in _expand_namespace_matches(using_ns, namespace_to_files):
                if target == source:
                    continue
                target_ns = file_to_namespace.get(target)
                if allowed_namespaces is not None and target_ns and target_ns not in allowed_namespaces:
                    continue
                graph[source]["imports"].add(target)
                graph[target]["importers"].add(source)

    return finalize_graph(dict(graph))


def cmd_deps(args):
    """Show dependency info for a specific C# file or top coupled files."""
    graph = build_dep_graph(Path(args.path))

    if getattr(args, "file", None):
        coupling = get_coupling_score(args.file, graph)
        if getattr(args, "json", False):
            import json
            print(json.dumps({"file": rel(args.file), **coupling}, indent=2))
            return
        print(c(f"\nDependency info: {rel(args.file)}\n", "bold"))
        print(f"  Fan-in (importers):  {coupling['fan_in']}")
        print(f"  Fan-out (imports):   {coupling['fan_out']}")
        print(f"  Instability:         {coupling['instability']}")
        return

    by_importers = sorted(
        graph.items(), key=lambda kv: (-kv[1].get("importer_count", 0), rel(kv[0]))
    )
    if getattr(args, "json", False):
        import json
        top = by_importers[: getattr(args, "top", 20)]
        print(
            json.dumps(
                {
                    "files": len(graph),
                    "entries": [
                        {
                            "file": rel(filepath),
                            "importers": entry.get("importer_count", 0),
                            "imports": entry.get("import_count", 0),
                        }
                        for filepath, entry in top
                    ],
                },
                indent=2,
            )
        )
        return

    print(c(f"\nC# dependency graph: {len(graph)} files\n", "bold"))
    rows = []
    for filepath, entry in by_importers[: getattr(args, "top", 20)]:
        rows.append(
            [
                rel(filepath),
                str(entry.get("importer_count", 0)),
                str(entry.get("import_count", 0)),
            ]
        )
    if rows:
        print_table(["File", "Importers", "Imports"], rows, [70, 9, 7])


def cmd_cycles(args):
    """Show import cycles in C# source files."""
    graph = build_dep_graph(Path(args.path))
    cycles, _ = detect_cycles(graph)

    if getattr(args, "json", False):
        import json
        print(
            json.dumps(
                {
                    "count": len(cycles),
                    "cycles": [
                        {"length": cy["length"], "files": [rel(f) for f in cy["files"]]}
                        for cy in cycles
                    ],
                },
                indent=2,
            )
        )
        return

    if not cycles:
        print(c("No import cycles found.", "green"))
        return

    print(c(f"\nImport cycles: {len(cycles)}\n", "bold"))
    for cy in cycles[: getattr(args, "top", 20)]:
        files = [rel(f) for f in cy["files"]]
        print(f"  [{cy['length']} files] {' -> '.join(files[:6])}" +
              (f" -> +{len(files) - 6}" if len(files) > 6 else ""))
