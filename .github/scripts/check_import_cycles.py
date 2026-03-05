"""Fail CI when new scoped import cycles appear."""

from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from pathlib import Path


def _iter_runtime_python_files(package_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(package_root.rglob("*.py")):
        parts = path.relative_to(package_root).parts
        if "tests" in parts:
            continue
        files.append(path)
    return files


def _module_name(package_name: str, package_root: Path, path: Path) -> str:
    rel = path.relative_to(package_root).with_suffix("")
    return f"{package_name}." + ".".join(rel.parts)


def _resolve_relative_module_name(current_module: str, level: int, module: str | None) -> str:
    current_package_parts = current_module.split(".")[:-1]
    keep = len(current_package_parts) - level + 1
    if keep < 0:
        keep = 0
    base = current_package_parts[:keep]
    if module:
        base.extend(module.split("."))
    return ".".join(base)


def _closest_known_module(import_name: str, known_modules: set[str]) -> str | None:
    candidate = import_name
    while candidate:
        if candidate in known_modules:
            return candidate
        if "." not in candidate:
            return None
        candidate = candidate.rsplit(".", 1)[0]
    return None


def _build_module_index(package_name: str, package_root: Path) -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in _iter_runtime_python_files(package_root):
        module = _module_name(package_name, package_root, path)
        modules[module] = path
        if module.endswith(".__init__"):
            modules[module[: -len(".__init__")]] = path
    return modules


def _build_import_graph(modules: dict[str, Path], package_name: str) -> dict[str, set[str]]:
    known_modules = set(modules)
    graph: dict[str, set[str]] = defaultdict(set)
    for module, path in modules.items():
        if module.endswith(".__init__"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        import_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                import_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    import_names.append(
                        _resolve_relative_module_name(module, node.level, node.module)
                    )
                elif node.module:
                    import_names.append(node.module)
        for import_name in import_names:
            if not import_name.startswith(package_name):
                continue
            target = _closest_known_module(import_name, known_modules)
            if target and target != module:
                graph[module].add(target)
    return graph


def _tarjan_scc(graph: dict[str, set[str]], modules: set[str]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in graph.get(node, set()):
            if neighbor not in indexes:
                visit(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indexes[neighbor])
        if lowlinks[node] != indexes[node]:
            return
        component: list[str] = []
        while True:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        components.append(component)

    for module in sorted(modules):
        if module not in indexes and not module.endswith(".__init__"):
            visit(module)
    return components


def _load_allowlist(path: Path) -> set[tuple[str, ...]]:
    if not path.exists():
        raise FileNotFoundError(f"allowlist not found: {path}")
    allowed: set[tuple[str, ...]] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        modules = tuple(sorted(part.strip() for part in line.split(",") if part.strip()))
        if len(modules) < 2:
            continue
        allowed.add(modules)
    return allowed


def _canonical_cycle(component: list[str]) -> tuple[str, ...]:
    return tuple(sorted(component))


def _intersects_scope(component: tuple[str, ...], scope_prefixes: tuple[str, ...]) -> bool:
    if not scope_prefixes:
        return True
    for module in component:
        for prefix in scope_prefixes:
            if module.startswith(prefix):
                return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root (defaults to this script's repo).",
    )
    parser.add_argument(
        "--package-name",
        default="desloppify",
        help="Top-level package to analyze.",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        required=True,
        help="Path to cycle allowlist file.",
    )
    parser.add_argument(
        "--scope-prefix",
        action="append",
        default=[],
        help="Limit gating to SCCs intersecting this module prefix (repeatable).",
    )
    args = parser.parse_args()

    package_root = args.repo_root / args.package_name
    modules = _build_module_index(args.package_name, package_root)
    graph = _build_import_graph(modules, args.package_name)
    components = _tarjan_scc(graph, set(modules))

    scoped_cycles = {
        _canonical_cycle(component)
        for component in components
        if len(component) > 1
        and _intersects_scope(_canonical_cycle(component), tuple(args.scope_prefix))
    }

    allowlist = _load_allowlist(args.allowlist)
    unexpected = sorted(scoped_cycles - allowlist)
    stale = sorted(allowlist - scoped_cycles)

    if unexpected:
        print("Detected unexpected scoped import cycles:", file=sys.stderr)
        for cycle in unexpected:
            print(f"  - {', '.join(cycle)}", file=sys.stderr)
        print(
            f"Allowlist path: {args.allowlist}. "
            "Add only intentional SCCs after architecture review.",
            file=sys.stderr,
        )
        return 1

    print(f"Scoped cycle gate passed ({len(scoped_cycles)} SCCs matched allowlist).")
    if stale:
        print(
            "Warning: stale cycle allowlist entries (safe to remove):",
            file=sys.stderr,
        )
        for cycle in stale:
            print(f"  - {', '.join(cycle)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
