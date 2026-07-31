"""Subjective code review: context building, file selection, and issue import.

Desloppify prepares structured review data (context + file batches + prompts)
for an AI agent to evaluate. The agent returns structured issues that are
imported back into state like any other detector.

Ownership boundary:
- ``app.commands.review`` owns workflow orchestration and CLI policy.
- ``intelligence.review`` owns domain helpers (context, selection, prepare,
  import, remediation) with no command orchestration.

No LLM calls happen here — this package is pure Python domain logic.
"""

from pathlib import Path
from typing import Any

from desloppify.engine._state.schema import StateModel, utc_now
from desloppify.intelligence.integrity import (
    is_holistic_subjective_issue,
    is_subjective_review_open,
    subjective_review_open_breakdown,
    unassessed_subjective_dimensions,
)
from desloppify.intelligence.review.context import ReviewContext, build_review_context
from desloppify.intelligence.review.context_holistic.orchestrator import (
    build_holistic_context,
)
from desloppify.intelligence.review.dimensions.data import load_dimensions_for_lang
from desloppify.intelligence.review.dimensions.holistic import (
    DIMENSION_PROMPTS,
    DIMENSIONS,
    REVIEW_SYSTEM_PROMPT,
)
from desloppify.intelligence.review.dimensions.lang import (
    HOLISTIC_DIMENSIONS_BY_LANG,
    LANG_GUIDANCE,
    get_lang_guidance,
)
from desloppify.intelligence.review.dimensions.selection import resolve_dimensions
from desloppify.intelligence.review.importing.contracts_types import ReviewImportPayload
from desloppify.intelligence.review.personas import PERSONAS, Persona, assign_personas
from desloppify.intelligence.review.policy import (
    DimensionPolicy,
    append_custom_dimensions,
    build_dimension_policy,
    filter_assessments_for_scoring,
    is_allowed_dimension,
    normalize_assessment_inputs,
    normalize_dimension_inputs,
)
from desloppify.intelligence.review.prepare import (
    HolisticReviewPrepareOptions,
    ReviewPrepareOptions,
    prepare_holistic_review,
    prepare_review,
)
from desloppify.intelligence.review.prepare_batches_builders import (
    build_investigation_batches,
)
from desloppify.intelligence.review.remediation import generate_remediation_plan
from desloppify.intelligence.review.selection import (
    LOW_VALUE_NAMES,
    hash_file,
    is_low_value_file,
    select_files_for_review,
)


def import_review_issues(
    issues_data: ReviewImportPayload,
    state: StateModel,
    lang_name: str,
    *,
    project_root: Path | str | None = None,
    utc_now_fn=utc_now,
) -> dict[str, Any]:
    """Lazy wrapper to avoid import cycles during package initialization."""
    from desloppify.intelligence.review.importing.per_file import (
        import_review_issues as _import_review_issues,
    )

    return _import_review_issues(
        issues_data,
        state,
        lang_name,
        project_root=project_root,
        utc_now_fn=utc_now_fn,
    )


def import_holistic_issues(
    issues_data: ReviewImportPayload,
    state: StateModel,
    lang_name: str,
    *,
    project_root: Path | str | None = None,
    preserve_open_issue_ids: set[str] | None = None,
    utc_now_fn=utc_now,
) -> dict[str, Any]:
    """Lazy wrapper to avoid import cycles during package initialization."""
    from desloppify.intelligence.review.importing.holistic import (
        import_holistic_issues as _import_holistic_issues,
    )

    return _import_holistic_issues(
        issues_data,
        state,
        lang_name,
        project_root=project_root,
        preserve_open_issue_ids=preserve_open_issue_ids,
        utc_now_fn=utc_now_fn,
    )

__all__ = [
    # dimensions
    "DIMENSIONS",
    "DIMENSION_PROMPTS",
    "REVIEW_SYSTEM_PROMPT",
    "HOLISTIC_DIMENSIONS_BY_LANG",
    "LANG_GUIDANCE",
    "get_lang_guidance",
    "load_dimensions_for_lang",
    "resolve_dimensions",
    # policy
    "DimensionPolicy",
    "append_custom_dimensions",
    "build_dimension_policy",
    "filter_assessments_for_scoring",
    "is_allowed_dimension",
    "normalize_assessment_inputs",
    "normalize_dimension_inputs",
    # context
    "ReviewContext",
    "build_review_context",
    "build_holistic_context",
    # selection
    "select_files_for_review",
    "hash_file",
    "LOW_VALUE_NAMES",
    "is_low_value_file",
    # prepare
    "ReviewPrepareOptions",
    "HolisticReviewPrepareOptions",
    "prepare_review",
    "prepare_holistic_review",
    "build_investigation_batches",
    "PERSONAS",
    "Persona",
    "assign_personas",
    # import
    "import_review_issues",
    "import_holistic_issues",
    # remediation
    "generate_remediation_plan",
    # integrity
    "is_subjective_review_open",
    "is_holistic_subjective_issue",
    "subjective_review_open_breakdown",
    "unassessed_subjective_dimensions",
]
