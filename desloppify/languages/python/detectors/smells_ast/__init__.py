"""AST-based Python code smell detectors.

Public API is intentionally narrow.
"""

from __future__ import annotations

from desloppify.languages.python.detectors.smells_ast._dispatch import (
    _detect_ast_smells as detect_ast_smells,
)
from desloppify.languages.python.detectors.smells_ast._source_detectors import (
    _collect_module_constants as collect_module_constants,
)
from desloppify.languages.python.detectors.smells_ast._source_detectors import (
    _detect_duplicate_constants as detect_duplicate_constants,
)
from desloppify.languages.python.detectors.smells_ast._source_detectors import (
    _detect_star_import_no_all as detect_star_import_no_all,
)
from desloppify.languages.python.detectors.smells_ast._source_detectors import (
    _detect_vestigial_parameter as detect_vestigial_parameter,
)

__all__ = [
    "collect_module_constants",
    "detect_ast_smells",
    "detect_duplicate_constants",
    "detect_star_import_no_all",
    "detect_vestigial_parameter",
]
