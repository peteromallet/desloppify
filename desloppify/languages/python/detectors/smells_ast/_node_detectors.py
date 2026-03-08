"""Compatibility facade for Python AST node detectors."""

from __future__ import annotations

from desloppify.languages.python.detectors.smells_ast._node_detectors_basic import (
    _detect_dead_functions,
    _detect_deferred_imports,
    _detect_inline_classes,
    _detect_monster_functions,
    _is_test_file,
)
from desloppify.languages.python.detectors.smells_ast._node_detectors_complexity import (
    _compute_cyclomatic_complexity,
    _detect_high_cyclomatic_complexity,
    _detect_lru_cache_mutable,
)
from desloppify.languages.python.detectors.smells_ast._node_detectors_nesting import (
    _collect_nested_lambdas,
    _collect_single_list_assignments,
    _detect_mutable_ref_hack,
    _detect_nested_closures,
    _find_subscript_zero_refs,
    _format_inner_def_names,
    _walk_inner_defs,
)

__all__ = [
    "_collect_nested_lambdas",
    "_collect_single_list_assignments",
    "_compute_cyclomatic_complexity",
    "_detect_dead_functions",
    "_detect_deferred_imports",
    "_detect_high_cyclomatic_complexity",
    "_detect_inline_classes",
    "_detect_lru_cache_mutable",
    "_detect_monster_functions",
    "_detect_mutable_ref_hack",
    "_detect_nested_closures",
    "_find_subscript_zero_refs",
    "_format_inner_def_names",
    "_is_test_file",
    "_walk_inner_defs",
]
