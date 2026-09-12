"""Orchestration for Python AST smell detectors."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import partial

from desloppify.languages.python.detectors.smells_ast._node_detectors_basic import (
    _detect_dead_functions,
    _detect_deferred_imports,
    _detect_inline_classes,
    _detect_monster_functions,
)
from desloppify.languages.python.detectors.smells_ast._node_detectors_complexity import (
    _detect_high_cyclomatic_complexity,
    _detect_lru_cache_mutable,
)
from desloppify.languages.python.detectors.smells_ast._node_detectors_nesting import (
    _detect_mutable_ref_hack,
    _detect_nested_closures,
)
from desloppify.languages.python.detectors.smells_ast._tree_context_callbacks import (
    _detect_callback_logging,
)
from desloppify.languages.python.detectors.smells_ast._tree_context_paths import (
    _detect_hardcoded_path_sep,
)
from desloppify.languages.python.detectors.smells_ast._tree_quality_detectors import (
    _detect_annotation_quality,
    _detect_constant_return,
    _detect_del_param,
    _detect_noop_function,
    _detect_optional_param_sprawl,
    _detect_unreachable_code,
)
from desloppify.languages.python.detectors.smells_ast._tree_safety_detectors import (
    _detect_import_time_boundary_mutations,
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

SmellCounts = dict[str, list[SmellMatch]]


@dataclass(frozen=True)
class _NodeDetectorSpec:
    smell_id: str
    collect: NodeCollector


@dataclass(frozen=True)
class _TreeDetectorSpec:
    smell_id: str
    collect: TreeCollector


NODE_DETECTORS: tuple[_NodeDetectorSpec, ...] = (
    _NodeDetectorSpec("monster_function", _detect_monster_functions),
    _NodeDetectorSpec("dead_function", _detect_dead_functions),
    _NodeDetectorSpec("deferred_import", _detect_deferred_imports),
    _NodeDetectorSpec("inline_class", _detect_inline_classes),
    _NodeDetectorSpec("lru_cache_mutable", _detect_lru_cache_mutable),
    _NodeDetectorSpec("nested_closure", _detect_nested_closures),
    _NodeDetectorSpec("mutable_ref_hack", _detect_mutable_ref_hack),
    _NodeDetectorSpec("high_cyclomatic_complexity", _detect_high_cyclomatic_complexity),
)


TREE_DETECTORS: tuple[_TreeDetectorSpec, ...] = (
    _TreeDetectorSpec("subprocess_no_timeout", _detect_subprocess_no_timeout),
    _TreeDetectorSpec("unsafe_file_write", _detect_unsafe_file_write),
    _TreeDetectorSpec("unreachable_code", _detect_unreachable_code),
    _TreeDetectorSpec("constant_return", _detect_constant_return),
    _TreeDetectorSpec("regex_backtrack", _detect_regex_backtrack),
    _TreeDetectorSpec("naive_comment_strip", _detect_naive_comment_strip),
    _TreeDetectorSpec("callback_logging", _detect_callback_logging),
    _TreeDetectorSpec("hardcoded_path_sep", _detect_hardcoded_path_sep),
    _TreeDetectorSpec("noop_function", _detect_noop_function),
    _TreeDetectorSpec("sys_exit_in_library", _detect_sys_exit_in_library),
    _TreeDetectorSpec(
        "import_path_mutation",
        partial(_detect_import_time_boundary_mutations, smell_id="import_path_mutation"),
    ),
    _TreeDetectorSpec(
        "import_env_mutation",
        partial(_detect_import_time_boundary_mutations, smell_id="import_env_mutation"),
    ),
    _TreeDetectorSpec(
        "import_runtime_init",
        partial(_detect_import_time_boundary_mutations, smell_id="import_runtime_init"),
    ),
    _TreeDetectorSpec("silent_except", _detect_silent_except),
    _TreeDetectorSpec("optional_param_sprawl", _detect_optional_param_sprawl),
    _TreeDetectorSpec("annotation_quality", _detect_annotation_quality),
    _TreeDetectorSpec("del_param", _detect_del_param),
)


def detect_ast_smells(
    filepath: str,
    content: str,
    smell_counts: SmellCounts,
    *,
    return_none_callable_default_providers: frozenset[tuple[str, str]] = frozenset(),
) -> None:
    """Detect AST-based code smells using registry-driven collector dispatch."""
    try:
        tree = ast.parse(content, filename=filepath)
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
            if spec.smell_id == "dead_function":
                matches.extend(
                    _detect_dead_functions(
                        filepath,
                        fn_node,
                        tree,
                        return_none_callable_default_providers=(
                            return_none_callable_default_providers
                        ),
                    )
                )
            else:
                matches.extend(spec.collect(filepath, fn_node, tree))
        merge_smell_matches(smell_counts, spec.smell_id, matches)

    for spec in TREE_DETECTORS:
        matches = spec.collect(filepath, tree, all_nodes)
        merge_smell_matches(smell_counts, spec.smell_id, matches)
