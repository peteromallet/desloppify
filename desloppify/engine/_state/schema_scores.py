"""Score/value accessor helpers for state schema payloads."""

from __future__ import annotations

from dataclasses import is_dataclass
from pathlib import Path
from typing import Any


def json_default(obj: Any) -> Any:
    """JSON serializer fallback for known non-JSON-native state values."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, Path):
        return str(obj).replace("\\", "/")
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if is_dataclass(obj):
        # Handle dataclass instances with Path attributes
        return {k: json_default(v) for k, v in vars(obj).items()}
    if isinstance(obj, dict):
        return {k: json_default(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_default(item) for item in obj]
    raise TypeError(
        f"Object of type {type(obj).__name__} is not JSON serializable: {obj!r}"
    )


def get_overall_score(state: dict[str, Any]) -> float | None:
    value = state.get("overall_score")
    return float(value) if isinstance(value, int | float) else None


def get_objective_score(state: dict[str, Any]) -> float | None:
    value = state.get("objective_score")
    return float(value) if isinstance(value, int | float) else None


def get_strict_score(state: dict[str, Any]) -> float | None:
    value = state.get("strict_score")
    return float(value) if isinstance(value, int | float) else None


def get_verified_strict_score(state: dict[str, Any]) -> float | None:
    value = state.get("verified_strict_score")
    return float(value) if isinstance(value, int | float) else None


__all__ = [
    "get_objective_score",
    "get_overall_score",
    "get_strict_score",
    "get_verified_strict_score",
    "json_default",
]
