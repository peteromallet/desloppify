"""Legacy subjective dimension defaults preserved for backward compatibility."""

from __future__ import annotations

from desloppify.base.subjective_dimension_catalog import DISPLAY_NAMES
from desloppify.base.subjective_dimension_catalog import (
    RESET_ON_SCAN_DIMENSIONS as LEGACY_RESET_ON_SCAN_DIMENSIONS,
)
from desloppify.base.subjective_dimension_catalog import (
    WEIGHT_BY_DIMENSION as LEGACY_WEIGHT_BY_DIMENSION,
)

LEGACY_DISPLAY_NAMES: dict[str, str] = DISPLAY_NAMES

__all__ = [
    "LEGACY_DISPLAY_NAMES",
    "LEGACY_RESET_ON_SCAN_DIMENSIONS",
    "LEGACY_WEIGHT_BY_DIMENSION",
]
