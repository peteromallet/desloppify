"""Direct coverage tests for holistic budget_abstractions re-export surface."""

from __future__ import annotations

from desloppify.intelligence.review.context_holistic import (
    budget_abstractions as abstractions_mod,
    budget_abstractions_axes as axes_mod,
    budget_abstractions_scan as scan_mod,
)


def test_budget_abstractions_exports_expected_symbols() -> None:
    expected = {
        "_abstractions_context",
        "_assemble_context",
        "_build_abstraction_leverage_context",
        "_build_definition_directness_context",
        "_build_delegation_density_context",
        "_build_indirection_cost_context",
        "_build_interface_honesty_context",
        "_build_type_discipline_context",
        "_compute_sub_axes",
    }
    assert set(abstractions_mod.__all__) == expected


def test_budget_abstractions_re_exports_reference_source_modules() -> None:
    assert abstractions_mod._abstractions_context is scan_mod._abstractions_context
    assert abstractions_mod._assemble_context is axes_mod._assemble_context
    assert (
        abstractions_mod._build_abstraction_leverage_context
        is axes_mod._build_abstraction_leverage_context
    )
    assert (
        abstractions_mod._build_definition_directness_context
        is axes_mod._build_definition_directness_context
    )
    assert (
        abstractions_mod._build_delegation_density_context
        is axes_mod._build_delegation_density_context
    )
    assert (
        abstractions_mod._build_indirection_cost_context
        is axes_mod._build_indirection_cost_context
    )
    assert (
        abstractions_mod._build_interface_honesty_context
        is axes_mod._build_interface_honesty_context
    )
    assert (
        abstractions_mod._build_type_discipline_context
        is axes_mod._build_type_discipline_context
    )
    assert abstractions_mod._compute_sub_axes is axes_mod._compute_sub_axes


def test_budget_abstractions_compute_sub_axes_callable_via_re_export() -> None:
    sub_axes = abstractions_mod._compute_sub_axes(
        wrapper_rate=0.1,
        util_files=[],
        indirection_hotspots=[],
        wide_param_bags=[],
        one_impl_interfaces=[],
        delegation_classes=[],
        facade_modules=[],
        typed_dict_violation_files=set(),
        total_typed_dict_violations=0,
    )
    assert set(sub_axes) == {
        "abstraction_leverage",
        "indirection_cost",
        "interface_honesty",
        "delegation_density",
        "definition_directness",
        "type_discipline",
    }

