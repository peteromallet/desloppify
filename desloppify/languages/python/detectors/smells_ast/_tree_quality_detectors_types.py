"""Type-signature quality detectors split from tree_quality_detectors."""

from __future__ import annotations

import ast

from desloppify.languages.python.detectors.smells_ast._shared import _iter_nodes


def _detect_optional_param_sprawl(
    filepath: str,
    tree: ast.Module,
    smell_counts: dict[str, list],
    *,
    all_nodes: tuple[ast.AST, ...] | None = None,
):
    """Flag functions with too many optional parameters."""
    dataclass_classes: set[str] = set()
    for node in _iter_nodes(tree, all_nodes, ast.ClassDef):
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Name) and dec.id == "dataclass") or (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Name)
                and dec.func.id == "dataclass"
            ):
                dataclass_classes.add(node.name)

    for node in _iter_nodes(tree, all_nodes, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name.startswith("test_"):
            continue
        if node.name == "__init__":
            parent_is_dataclass = False
            for parent in ast.walk(tree):
                if (
                    isinstance(parent, ast.ClassDef)
                    and parent.name in dataclass_classes
                ):
                    if node in ast.walk(parent):
                        parent_is_dataclass = True
                        break
            if parent_is_dataclass:
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
            smell_counts["optional_param_sprawl"].append(
                {
                    "file": filepath,
                    "line": node.lineno,
                    "content": (
                        f"{node.name}() — {total} params ({required} required, "
                        f"{optional} optional) — consider a config object"
                    ),
                }
            )


_BARE_TYPES = {"dict", "list", "set", "tuple", "Dict", "List", "Set", "Tuple"}


def _detect_annotation_quality(
    filepath: str,
    tree: ast.Module,
    smell_counts: dict[str, list],
    *,
    all_nodes: tuple[ast.AST, ...] | None = None,
):
    """Flag loose type annotations: bare containers, bare Callable, missing returns."""
    for node in _iter_nodes(tree, all_nodes, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name.startswith("_") and not node.name.startswith("__"):
            continue
        if node.name.startswith("test_"):
            continue

        ret = node.returns
        if ret is not None:
            if isinstance(ret, ast.Name) and ret.id in _BARE_TYPES:
                smell_counts["annotation_quality"].append(
                    {
                        "file": filepath,
                        "line": node.lineno,
                        "content": f"{node.name}() -> {ret.id} — use {ret.id}[...] for specific types",
                    }
                )
            elif isinstance(ret, ast.Attribute) and ret.attr in _BARE_TYPES:
                smell_counts["annotation_quality"].append(
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
                    smell_counts["annotation_quality"].append(
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
                smell_counts["annotation_quality"].append(
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
                smell_counts["annotation_quality"].append(
                    {
                        "file": filepath,
                        "line": node.lineno,
                        "content": (
                            f"{node.name}({arg.arg}: Callable) — "
                            f"specify Callable[[params], return_type]"
                        ),
                    }
                )
