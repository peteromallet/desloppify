"""Regression tests for ContextVar propagation in prefetch executor.

``_PREFETCH_EXECUTOR`` is a ``ThreadPoolExecutor`` that does not automatically
carry ``ContextVar`` values into worker threads. Runtime settings that live in
a context variable — most importantly user-configured path exclusions consumed
via ``get_exclusions()`` — must still be observable from work submitted to the
pool, otherwise detectors such as jscpd and the security prefetch ignore the
current scan's configuration.
"""

from __future__ import annotations

from desloppify.base.discovery.source import get_exclusions, set_exclusions
from desloppify.base.runtime_state import runtime_scope
from desloppify.languages._framework.base.shared_phases_review import (
    _submit_with_context,
)


def test_submit_with_context_preserves_runtime_exclusions() -> None:
    with runtime_scope():
        set_exclusions(["tmp", "backend/tmp", ".refs"])

        def _read_exclusions() -> tuple[str, ...]:
            return get_exclusions()

        future = _submit_with_context(_read_exclusions)
        assert future.result(timeout=5) == ("tmp", "backend/tmp", ".refs")


def test_submit_with_context_isolates_between_scopes() -> None:
    with runtime_scope():
        set_exclusions(["scope_a"])

        def _snapshot() -> tuple[str, ...]:
            return get_exclusions()

        first = _submit_with_context(_snapshot).result(timeout=5)

    with runtime_scope():
        set_exclusions(["scope_b"])
        second = _submit_with_context(_snapshot).result(timeout=5)

    assert first == ("scope_a",)
    assert second == ("scope_b",)
