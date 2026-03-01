"""Shared dynamic path proxy for runtime-root-aware path exports."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


class DynamicPathProxy:
    """Path-like proxy that resolves its underlying path on each access."""

    def __init__(self, resolver: Callable[[], Path], *, label: str) -> None:
        self._resolver = resolver
        self._label = label

    def _value(self) -> Path:
        return self._resolver()

    def __fspath__(self) -> str:
        return str(self._value())

    def __str__(self) -> str:
        return str(self._value())

    def __repr__(self) -> str:
        return f"{self._label}({self._value()!s})"

    def __truediv__(self, other: object) -> Path:
        return self._value() / other

    def __rtruediv__(self, other: object) -> Path:
        return Path(other) / self._value()

    def __getattr__(self, name: str) -> object:
        return getattr(self._value(), name)


__all__ = ["DynamicPathProxy"]
