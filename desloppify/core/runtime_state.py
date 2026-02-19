"""Runtime state model for exclusions and in-memory caches."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path


class ExclusionConfig:
    """In-memory exclusion configuration shared across scans."""

    def __init__(self) -> None:
        self.values: tuple[str, ...] = ()


class FileTextCache:
    """Optional read-through file-text cache used by scan/review passes."""

    def __init__(self) -> None:
        self._enabled = False
        self._values: dict[str, str | None] = {}

    def enable(self) -> None:
        self._enabled = True
        self._values.clear()

    def disable(self) -> None:
        self._enabled = False
        self._values.clear()

    def read(self, filepath: str) -> str | None:
        if self._enabled and filepath in self._values:
            return self._values[filepath]

        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError:
            content = None
        if self._enabled:
            self._values[filepath] = content
        return content


class CacheEnabledFlag:
    """Mutable bool-like wrapper to avoid rebinding during tests."""

    def __init__(self) -> None:
        self.value = False

    def set(self, enabled: bool) -> None:
        self.value = enabled

    def __bool__(self) -> bool:
        return self.value

    def __repr__(self) -> str:
        return str(self.value)


class SourceFileCache:
    """Small FIFO cache for source-file discovery results."""

    def __init__(self, *, max_entries: int) -> None:
        self.max_entries = max_entries
        self.values: dict[tuple, tuple[str, ...]] = {}

    def get(self, key: tuple) -> tuple[str, ...] | None:
        return self.values.get(key)

    def put(self, key: tuple, value: tuple[str, ...]) -> None:
        if len(self.values) >= self.max_entries:
            self.values.pop(next(iter(self.values)))
        self.values[key] = value

    def clear(self) -> None:
        self.values.clear()


@dataclass
class RuntimeContext:
    """Mutable runtime container for exclusion and cache state."""

    exclusion_config: ExclusionConfig = field(default_factory=ExclusionConfig)
    file_text_cache: FileTextCache = field(default_factory=FileTextCache)
    cache_enabled: CacheEnabledFlag = field(default_factory=CacheEnabledFlag)
    source_file_cache: SourceFileCache = field(
        default_factory=lambda: SourceFileCache(max_entries=16)
    )


_PROCESS_RUNTIME_CONTEXT = RuntimeContext()
_RUNTIME_CONTEXT: ContextVar[RuntimeContext | None] = ContextVar(
    "desloppify_runtime_context",
    default=None,
)


def make_runtime_context(*, source_file_cache_max_entries: int = 16) -> RuntimeContext:
    """Create an isolated runtime context."""
    return RuntimeContext(
        source_file_cache=SourceFileCache(max_entries=source_file_cache_max_entries)
    )


def current_runtime_context() -> RuntimeContext:
    """Return the active runtime context (or process fallback)."""
    runtime = _RUNTIME_CONTEXT.get()
    if runtime is not None:
        return runtime
    return _PROCESS_RUNTIME_CONTEXT


@contextmanager
def runtime_scope(runtime: RuntimeContext | None = None):
    """Run code with an isolated runtime context."""
    active = runtime or make_runtime_context()
    token = _RUNTIME_CONTEXT.set(active)
    try:
        yield active
    finally:
        _RUNTIME_CONTEXT.reset(token)


def set_process_runtime_context(runtime: RuntimeContext | None = None) -> RuntimeContext:
    """Replace process fallback runtime context (primarily for tests)."""
    global _PROCESS_RUNTIME_CONTEXT
    _PROCESS_RUNTIME_CONTEXT = runtime or make_runtime_context()
    return _PROCESS_RUNTIME_CONTEXT


__all__ = [
    "CacheEnabledFlag",
    "ExclusionConfig",
    "FileTextCache",
    "RuntimeContext",
    "SourceFileCache",
    "current_runtime_context",
    "make_runtime_context",
    "runtime_scope",
    "set_process_runtime_context",
]
