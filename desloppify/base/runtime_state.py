"""Runtime state model for exclusions and in-memory caches."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path


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

    exclusions: tuple[str, ...] = ()
    project_root: Path | None = None
    query_file: Path | None = None
    file_text_cache: FileTextCache = field(default_factory=FileTextCache)
    cache_enabled: bool = False
    source_file_cache: SourceFileCache = field(
        default_factory=lambda: SourceFileCache(max_entries=16)
    )
    allow_unsafe_coerce: bool = False


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


__all__ = [
    "FileTextCache",
    "RuntimeContext",
    "SourceFileCache",
    "current_runtime_context",
    "make_runtime_context",
    "runtime_scope",
]
