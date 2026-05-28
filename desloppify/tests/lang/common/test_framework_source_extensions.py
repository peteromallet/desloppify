"""Tests for the registry-driven ``framework_source_extensions`` query.

The dep-graph builder in ``ts_build_dep_graph`` (and the TS plugin's
hand-rolled equivalent) reads framework source extensions from the
``FrameworkSpec`` registry rather than from a hardcoded tuple, so that
adding a new framework (e.g. Qwik) becomes a one-spec-file change with
zero infrastructure edits.
"""

from __future__ import annotations

import pytest

from desloppify.languages._framework.frameworks.registry import (
    FRAMEWORK_SPECS,
    _invalidate_extensions_cache,
    framework_source_extensions,
    register_framework_spec,
)
from desloppify.languages._framework.frameworks.types import (
    DetectionConfig,
    FrameworkSpec,
)


@pytest.fixture
def restore_registry():
    """Snapshot + restore FRAMEWORK_SPECS so tests can register/unregister freely.

    ``framework_source_extensions`` caches per-ecosystem results; the cache is
    invalidated automatically on ``register_framework_spec`` but bypassed by
    the direct dict mutations used here for teardown, so we invalidate
    explicitly to keep the cache aligned with the restored registry state.
    """
    snapshot = dict(FRAMEWORK_SPECS)
    yield
    FRAMEWORK_SPECS.clear()
    FRAMEWORK_SPECS.update(snapshot)
    _invalidate_extensions_cache()


def test_default_node_extensions_cover_astro_svelte_vue():
    """The built-in specs contribute .astro/.svelte/.vue under the node ecosystem."""
    exts = framework_source_extensions(ecosystem="node")
    assert ".astro" in exts
    assert ".svelte" in exts
    assert ".vue" in exts


def test_extensions_are_sorted_and_deduplicated(restore_registry):
    """Duplicate extensions across specs collapse to a single entry, sorted."""
    register_framework_spec(
        FrameworkSpec(
            id="astro-duplicate-for-test",
            label="Astro (duplicate for test)",
            ecosystem="node",
            detection=DetectionConfig(dependencies=("astro-clone",)),
            source_extensions=(".astro",),
        )
    )

    exts = framework_source_extensions(ecosystem="node")
    assert exts == tuple(sorted(set(exts)))
    assert exts.count(".astro") == 1


def test_specs_without_source_extensions_contribute_nothing(restore_registry):
    """NEXTJS_SPEC and other specs that don't declare source_extensions are not
    counted — their source files (.ts/.tsx/etc.) are already covered by the
    host language's extensions, so they have nothing to add here.
    """
    baseline = framework_source_extensions(ecosystem="node")
    register_framework_spec(
        FrameworkSpec(
            id="scanners-only-fixture",
            label="Scanners-only fixture",
            ecosystem="node",
            detection=DetectionConfig(dependencies=("scanners-only-fixture",)),
            # source_extensions left at default ()
        )
    )

    assert framework_source_extensions(ecosystem="node") == baseline


def test_ecosystem_filter_excludes_other_ecosystems(restore_registry):
    """A python-ecosystem spec's source extensions don't leak into a node query."""
    register_framework_spec(
        FrameworkSpec(
            id="jinja-fixture",
            label="Jinja (fixture)",
            ecosystem="python",
            detection=DetectionConfig(dependencies=("jinja2",)),
            source_extensions=(".jinja",),
        )
    )

    node_exts = framework_source_extensions(ecosystem="node")
    python_exts = framework_source_extensions(ecosystem="python")

    assert ".jinja" not in node_exts
    assert ".jinja" in python_exts


def test_repeated_calls_return_cached_tuple(restore_registry):
    """Per-ecosystem results are memoized and ``register_framework_spec`` invalidates."""
    first = framework_source_extensions(ecosystem="node")
    second = framework_source_extensions(ecosystem="node")
    # Same tuple identity proves we returned the cached value rather than
    # re-aggregating the registry on every call.
    assert first is second

    register_framework_spec(
        FrameworkSpec(
            id="cache-invalidation-fixture",
            label="Cache invalidation fixture",
            ecosystem="node",
            detection=DetectionConfig(dependencies=("never-installed",)),
            source_extensions=(".cache-invalidator",),
        )
    )

    third = framework_source_extensions(ecosystem="node")
    assert third is not first
    assert ".cache-invalidator" in third


def test_unfiltered_query_aggregates_across_ecosystems(restore_registry):
    """Querying without an ecosystem filter returns every registered extension."""
    register_framework_spec(
        FrameworkSpec(
            id="jinja-fixture-2",
            label="Jinja (fixture 2)",
            ecosystem="python",
            detection=DetectionConfig(dependencies=("jinja2-clone",)),
            source_extensions=(".jinja",),
        )
    )

    all_exts = framework_source_extensions()
    assert ".astro" in all_exts
    assert ".jinja" in all_exts
