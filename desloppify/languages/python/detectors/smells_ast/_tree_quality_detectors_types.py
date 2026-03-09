"""Type-signature quality detectors split from tree_quality_detectors."""

from __future__ import annotations

import ast

from desloppify.languages.python.detectors.smells_ast._helpers import _iter_nodes


def _is_dataclass_decorator(decorator: ast.AST) -> bool:
    """Return True when decorator is ``@dataclass`` (name or call form)."""
    return (
        isinstance(decorator, ast.Name)
        and decorator.id == "dataclass"
    ) or (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Name)
        and decorator.func.id == "dataclass"
    )


def _dataclass_init_node_ids(
    tree: ast.Module,
    *,
    all_nodes: tuple[ast.AST, ...] | None = None,
) -> set[int]:
    """Collect __init__ function node IDs that belong to dataclass classes."""
    init_ids: set[int] = set()
    for class_node in _iter_nodes(tree, all_nodes, ast.ClassDef):
        if not any(_is_dataclass_decorator(dec) for dec in class_node.decorator_list):
            continue
        for class_item in class_node.body:
            if isinstance(class_item, (ast.FunctionDef, ast.AsyncFunctionDef)) and class_item.name == "__init__":
                init_ids.add(id(class_item))
    return init_ids


def _detect_optional_param_sprawl(
    filepath: str,
    tree: ast.Module,
    *,
    all_nodes: tuple[ast.AST, ...] | None = None,
) -> list[dict]:
    """Flag functions with too many optional parameters."""
    dataclass_inits = _dataclass_init_node_ids(tree, all_nodes=all_nodes)

    results: list[dict] = []
    for node in _iter_nodes(tree, all_nodes, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name.startswith("test_"):
            continue
        if node.name == "__init__" and id(node) in dataclass_inits:
                continue

        args = node.args
        n_defaults = len(args.defaults)
        n_positional = len(args.args)
        if n_positional > 0 and args.args[0].arg in ("self", "cls"):
            n_positional -= 1

        kw_with_default = sum(1 for d in args.kw_defaults if d is not None)
        optional = n_defaults + kw_with_default
        required = n_positional - n_defaults + (len(args.kwonlyargs) - kw_with_default)
        total = required + optional

        if optional >= 4 and optional > required and total >= 5:
            results.append(
                {
                    "file": filepath,
                    "line": node.lineno,
                    "content": (
                        f"{node.name}() — {total} params ({required} required, "
                        f"{optional} optional) — consider a config object"
                    ),
                }
            )
    return results


_BARE_TYPES = {"dict", "list", "set", "tuple", "Dict", "List", "Set", "Tuple"}


def _detect_annotation_quality(
    filepath: str,
    tree: ast.Module,
    *,
    all_nodes: tuple[ast.AST, ...] | None = None,
) -> list[dict]:
    """Flag loose type annotations: bare containers, bare Callable, missing returns."""
    results: list[dict] = []
    for node in _iter_nodes(tree, all_nodes, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name.startswith("_") and not node.name.startswith("__"):
            continue
        if node.name.startswith("test_"):
            continue

        ret = node.returns
        if ret is not None:
            if isinstance(ret, ast.Name) and ret.id in _BARE_TYPES:
                results.append(
                    {
                        "file": filepath,
                        "line": node.lineno,
                        "content": f"{node.name}() -> {ret.id} — use {ret.id}[...] for specific types",
                    }
                )
            elif isinstance(ret, ast.Attribute) and ret.attr in _BARE_TYPES:
                results.append(
                    {
                        "file": filepath,
                        "line": node.lineno,
                        "content": f"{node.name}() -> {ret.attr} — use {ret.attr}[...] for specific types",
                    }
                )
        elif not node.name.startswith("__"):
            if hasattr(node, "end_lineno") and node.end_lineno:
                loc = node.end_lineno - node.lineno + 1
                if loc >= 10:
                    results.append(
                        {
                            "file": filepath,
                            "line": node.lineno,
                            "content": f"{node.name}() — public function ({loc} LOC) missing return type",
                        }
                    )

        all_args = node.args.args + node.args.kwonlyargs
        for arg in all_args:
            if arg.arg in ("self", "cls"):
                continue
            ann = arg.annotation
            if ann is None:
                continue
            if isinstance(ann, ast.Name) and ann.id == "Callable":
                results.append(
                    {
                        "file": filepath,
                        "line": node.lineno,
                        "content": (
                            f"{node.name}({arg.arg}: Callable) — "
                            f"specify Callable[[params], return_type]"
                        ),
                    }
                )
            elif isinstance(ann, ast.Attribute) and ann.attr == "Callable":
                results.append(
                    {
                        "file": filepath,
                        "line": node.lineno,
                        "content": (
                            f"{node.name}({arg.arg}: Callable) — "
                            f"specify Callable[[params], return_type]"
                        ),
                    }
                )
    return results
