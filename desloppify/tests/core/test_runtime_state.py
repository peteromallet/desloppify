"""Tests for scoped runtime state behavior."""

from __future__ import annotations

import desloppify.core.runtime_state as runtime_state
from desloppify.file_discovery import (
    disable_file_cache,
    enable_file_cache,
    get_exclusions,
    is_file_cache_enabled,
    set_exclusions,
)


def test_runtime_scope_isolates_exclusions():
    original = get_exclusions()
    set_exclusions(["global-only"])
    try:
        with runtime_state.runtime_scope(runtime_state.make_runtime_context()):
            assert get_exclusions() == ()
            set_exclusions(["scoped-only"])
            assert get_exclusions() == ("scoped-only",)

        assert get_exclusions() == ("global-only",)
    finally:
        set_exclusions(list(original))


def test_runtime_scope_restores_file_cache_flag():
    disable_file_cache()
    assert not is_file_cache_enabled()

    with runtime_state.runtime_scope(runtime_state.make_runtime_context()):
        assert not is_file_cache_enabled()
        enable_file_cache()
        assert is_file_cache_enabled()

    assert not is_file_cache_enabled()


def test_source_file_cache_is_scoped():
    key = ("scan", ".py")
    runtime_state.current_runtime_context().source_file_cache.clear()
    runtime_state.current_runtime_context().source_file_cache.put(key, ("global.py",))

    with runtime_state.runtime_scope(runtime_state.make_runtime_context()):
        cache = runtime_state.current_runtime_context().source_file_cache
        assert cache.get(key) is None
        cache.put(key, ("scoped.py",))
        assert cache.get(key) == ("scoped.py",)

    assert runtime_state.current_runtime_context().source_file_cache.get(key) == (
        "global.py",
    )
