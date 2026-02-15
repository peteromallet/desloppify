"""Subjective code review: context building, file selection, and finding import.

Desloppify prepares structured review data (context + file batches + prompts)
for an AI agent to evaluate. The agent returns structured findings that are
imported back into state like any other detector.

No LLM calls happen here — this module is pure Python.
"""

from .dimensions import (
    HOLISTIC_DIMENSIONS,
    HOLISTIC_DIMENSION_PROMPTS,
    HOLISTIC_REVIEW_SYSTEM_PROMPT,
    DEFAULT_DIMENSIONS,
    DIMENSION_PROMPTS,
    LANG_GUIDANCE,
    REVIEW_SYSTEM_PROMPT,
)
from .context import (
    ReviewContext,
    build_review_context,
    _serialize_context,
    _file_excerpt,
    _extract_imported_names,
    _abs,
    _dep_graph_lookup,
    _importer_count,
    _gather_ai_debt_signals,
    _gather_auth_context,
    _gather_migration_signals,
    _classify_error_strategy,
)
from .context_holistic import build_holistic_context
from .selection import (
    select_files_for_review,
    hash_file,
    _compute_review_priority,
    _get_file_findings,
    _count_fresh,
    _count_stale,
    LOW_VALUE_NAMES,
    MIN_REVIEW_LOC,
)
from .prepare import (
    prepare_review,
    prepare_holistic_review,
    _build_investigation_batches,
    _build_file_requests,
    _HOLISTIC_WORKFLOW,
    _rel_list,
)
from .import_findings import (
    import_review_findings,
    import_holistic_findings,
    _store_assessments,
    _extract_findings_and_assessments,
    _update_review_cache,
    _update_holistic_review_cache,
)
from .remediation import (
    generate_remediation_plan,
    _empty_plan,
)

__all__ = [
    # dimensions
    "HOLISTIC_DIMENSIONS", "HOLISTIC_DIMENSION_PROMPTS", "HOLISTIC_REVIEW_SYSTEM_PROMPT",
    "DEFAULT_DIMENSIONS", "DIMENSION_PROMPTS", "LANG_GUIDANCE", "REVIEW_SYSTEM_PROMPT",
    # context
    "ReviewContext", "build_review_context", "_serialize_context",
    "build_holistic_context", "_file_excerpt", "_extract_imported_names",
    "_abs", "_dep_graph_lookup", "_importer_count",
    "_gather_ai_debt_signals", "_gather_auth_context",
    "_gather_migration_signals", "_classify_error_strategy",
    # selection
    "select_files_for_review", "hash_file", "_compute_review_priority",
    "_get_file_findings", "_count_fresh", "_count_stale",
    "LOW_VALUE_NAMES", "MIN_REVIEW_LOC",
    # prepare
    "prepare_review", "prepare_holistic_review", "_build_investigation_batches",
    "_build_file_requests", "_HOLISTIC_WORKFLOW", "_rel_list",
    # import
    "import_review_findings", "import_holistic_findings",
    "_store_assessments", "_extract_findings_and_assessments",
    "_update_review_cache", "_update_holistic_review_cache",
    # remediation
    "generate_remediation_plan", "_empty_plan",
]
