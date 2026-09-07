"""Canonical public API for tree-sitter specs and phase factories.

Install with: ``pip install tree-sitter-language-pack``

Internal layout:
- ``specs``: language-spec catalogs and variants
- ``imports``: import graph + resolver/cache helpers
- ``analysis``: detectors/extractors/complexity helpers

Underscore-prefixed modules at this package root remain compatibility shims only.
New code and direct tests should import from the grouped namespaces above.
"""

from __future__ import annotations

import logging

from desloppify.base.output.fallbacks import log_best_effort_failure
from .types import TreeSitterLangSpec

logger = logging.getLogger(__name__)

_AVAILABLE = False
try:
    import tree_sitter_language_pack  # noqa: F401

    _AVAILABLE = True
except ImportError as exc:
    log_best_effort_failure(logger, "import tree_sitter_language_pack", exc)


def is_available() -> bool:
    """Return True if tree-sitter-language-pack is installed."""
    return _AVAILABLE


def enable_parse_cache() -> None:
    """Enable scan-scoped parse tree cache."""
    from .imports.cache import enable_parse_cache as _enable

    _enable()


def disable_parse_cache() -> None:
    """Disable parse tree cache and free memory."""
    from .imports.cache import disable_parse_cache as _disable

    _disable()


def is_parse_cache_enabled() -> bool:
    """Check if parse cache is currently enabled."""
    from .imports.cache import is_parse_cache_enabled as _is_enabled

    return _is_enabled()


def reset_script_import_caches(scan_path: str | None = None) -> None:
    """Clear script import resolver caches for a scan path or the whole process."""
    from .imports.resolvers_scripts import reset_script_import_caches as _reset

    _reset(scan_path)


PARSE_INIT_ERRORS: tuple[type[Exception], ...] = (
    ImportError,
    OSError,
    ValueError,
    RuntimeError,
)

from .specs.specs import (  # noqa: E402
    BASH_SPEC,
    CLOJURE_SPEC,
    CPP_SPEC,
    CSHARP_SPEC,
    C_SPEC,
    DART_SPEC,
    ELIXIR_SPEC,
    ERLANG_SPEC,
    FSHARP_SPEC,
    GDSCRIPT_SPEC,
    GO_SPEC,
    HASKELL_SPEC,
    JAVA_SPEC,
    JS_SPEC,
    JULIA_SPEC,
    KOTLIN_SPEC,
    LUA_SPEC,
    LUAU_SPEC,
    NIM_SPEC,
    OCAML_SPEC,
    PERL_SPEC,
    PHP_SPEC,
    POWERSHELL_SPEC,
    R_SPEC,
    RUBY_SPEC,
    RUST_SPEC,
    SCALA_SPEC,
    SWIFT_SPEC,
    TREESITTER_SPECS,
    TYPESCRIPT_SPEC,
    ZIG_SPEC,
)
from .phases import (  # noqa: E402
    all_treesitter_phases,
    make_ast_smells_phase,
    make_cohesion_phase,
    make_unused_imports_phase,
)


def get_spec(language: str) -> TreeSitterLangSpec | None:
    """Return tree-sitter spec for a language key, if configured."""
    key = str(language or "").strip().lower()
    if not key:
        return None
    return TREESITTER_SPECS.get(key)


def list_specs() -> dict[str, TreeSitterLangSpec]:
    """Return a shallow copy of the public tree-sitter spec registry."""
    return dict(TREESITTER_SPECS)


__all__ = [
    "BASH_SPEC",
    "CLOJURE_SPEC",
    "CPP_SPEC",
    "CSHARP_SPEC",
    "C_SPEC",
    "DART_SPEC",
    "ELIXIR_SPEC",
    "ERLANG_SPEC",
    "FSHARP_SPEC",
    "GDSCRIPT_SPEC",
    "GO_SPEC",
    "HASKELL_SPEC",
    "JAVA_SPEC",
    "JS_SPEC",
    "JULIA_SPEC",
    "KOTLIN_SPEC",
    "LUA_SPEC",
    "LUAU_SPEC",
    "NIM_SPEC",
    "OCAML_SPEC",
    "PARSE_INIT_ERRORS",
    "PERL_SPEC",
    "PHP_SPEC",
    "POWERSHELL_SPEC",
    "R_SPEC",
    "RUBY_SPEC",
    "RUST_SPEC",
    "SCALA_SPEC",
    "SWIFT_SPEC",
    "TREESITTER_SPECS",
    "TYPESCRIPT_SPEC",
    "TreeSitterLangSpec",
    "ZIG_SPEC",
    "all_treesitter_phases",
    "disable_parse_cache",
    "enable_parse_cache",
    "get_spec",
    "is_available",
    "is_parse_cache_enabled",
    "list_specs",
    "make_ast_smells_phase",
    "make_cohesion_phase",
    "make_unused_imports_phase",
    "reset_script_import_caches",
]
