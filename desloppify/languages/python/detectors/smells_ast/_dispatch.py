"""Orchestration for Python AST smell detectors."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from desloppify.languages.python.detectors.smells_ast._node_detectors import (
    _detect_dead_functions,
    _detect_deferred_imports,
    _detect_inline_classes,
    _detect_lru_cache_mutable,
    _detect_monster_functions,
)
from desloppify.languages.python.detectors.smells_ast._tree_context_detectors import (
    _detect_callback_logging,
    _detect_hardcoded_path_sep,
)
from desloppify.languages.python.detectors.smells_ast._tree_quality_detectors import (
    _detect_annotation_quality,
    _detect_constant_return,
    _detect_mutable_class_var,
    _detect_noop_function,
    _detect_optional_param_sprawl,
    _detect_unreachable_code,
)
from desloppify.languages.python.detectors.smells_ast._tree_safety_detectors import (
    _detect_import_time_boundary_mutations,
    _detect_lost_exception_context,
    _detect_naive_comment_strip,
    _detect_regex_backtrack,
    _detect_silent_except,
    _detect_subprocess_no_timeout,
    _detect_sys_exit_in_library,
    _detect_unsafe_file_write,
)
from desloppify.languages.python.detectors.smells_ast._types import (
    NodeCollector,
    SmellMatch,
    TreeCollector,
    merge_smell_matches,
)


def _collect_from_mutating(
    smell_id: str,
    detector,
    *args,
    **kwargs,
) -> list[SmellMatch]:
    """Adapter: run legacy mutating detector and return collected matches."""
    bucket: list[SmellMatch] = []
    detector(*args, {smell_id: bucket}, **kwargs)
    return bucket


@dataclass(frozen=True)
class _NodeDetectorSpec:
    smell_id: str
    collect: NodeCollector


@dataclass(frozen=True)
class _TreeDetectorSpec:
    smell_id: str
    collect: TreeCollector


NODE_DETECTORS: tuple[_NodeDetectorSpec, ...] = (
    _NodeDetectorSpec(
        "monster_function",
        lambda filepath, node, tree: _collect_from_mutating(
            "monster_function", _detect_monster_functions, filepath, node
        ),
    ),
    _NodeDetectorSpec(
        "dead_function",
        lambda filepath, node, tree: _collect_from_mutating(
            "dead_function", _detect_dead_functions, filepath, node
        ),
    ),
    _NodeDetectorSpec(
        "deferred_import",
        lambda filepath, node, tree: _collect_from_mutating(
            "deferred_import", _detect_deferred_imports, filepath, node
        ),
    ),
    _NodeDetectorSpec(
        "inline_class",
        lambda filepath, node, tree: _collect_from_mutating(
            "inline_class", _detect_inline_classes, filepath, node
        ),
    ),
    _NodeDetectorSpec(
        "lru_cache_mutable",
        lambda filepath, node, tree: _collect_from_mutating(
            "lru_cache_mutable", _detect_lru_cache_mutable, filepath, node, tree
        ),
    ),
)


TREE_DETECTORS: tuple[_TreeDetectorSpec, ...] = (
    _TreeDetectorSpec(
        "subprocess_no_timeout",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "subprocess_no_timeout",
            _detect_subprocess_no_timeout,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "mutable_class_var",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "mutable_class_var",
            _detect_mutable_class_var,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "unsafe_file_write",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "unsafe_file_write",
            _detect_unsafe_file_write,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "unreachable_code",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "unreachable_code",
            _detect_unreachable_code,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "constant_return",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "constant_return",
            _detect_constant_return,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "regex_backtrack",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "regex_backtrack",
            _detect_regex_backtrack,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "naive_comment_strip",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "naive_comment_strip",
            _detect_naive_comment_strip,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "callback_logging",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "callback_logging",
            _detect_callback_logging,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "hardcoded_path_sep",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "hardcoded_path_sep",
            _detect_hardcoded_path_sep,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "lost_exception_context",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "lost_exception_context",
            _detect_lost_exception_context,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "noop_function",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "noop_function",
            _detect_noop_function,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "sys_exit_in_library",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "sys_exit_in_library",
            _detect_sys_exit_in_library,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "import_path_mutation",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "import_path_mutation",
            _detect_import_time_boundary_mutations,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "import_env_mutation",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "import_env_mutation",
            _detect_import_time_boundary_mutations,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "import_runtime_init",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "import_runtime_init",
            _detect_import_time_boundary_mutations,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "silent_except",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "silent_except",
            _detect_silent_except,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "optional_param_sprawl",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "optional_param_sprawl",
            _detect_optional_param_sprawl,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
    _TreeDetectorSpec(
        "annotation_quality",
        lambda filepath, tree, all_nodes: _collect_from_mutating(
            "annotation_quality",
            _detect_annotation_quality,
            filepath,
            tree,
            all_nodes=all_nodes,
        ),
    ),
)


def _detect_ast_smells(filepath: str, content: str, smell_counts: dict[str, list]):
    """Detect AST-based code smells using registry-driven collector dispatch."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return

    # Build a single-walk context index for node-level detectors.
    all_nodes = tuple(ast.walk(tree))
    fn_nodes = tuple(
        node
        for node in all_nodes
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    )

    for spec in NODE_DETECTORS:
        matches: list[SmellMatch] = []
        for fn_node in fn_nodes:
            matches.extend(spec.collect(filepath, fn_node, tree))
        merge_smell_matches(smell_counts, spec.smell_id, matches)

    for spec in TREE_DETECTORS:
        matches = spec.collect(filepath, tree, all_nodes)
        merge_smell_matches(smell_counts, spec.smell_id, matches)
