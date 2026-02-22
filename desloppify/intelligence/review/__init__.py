"""Subjective code review: context building, file selection, and finding import.

Desloppify prepares structured review data (context + file batches + prompts)
for an AI agent to evaluate. The agent returns structured findings that are
imported back into state like any other detector.

No LLM calls happen here — this module is pure Python.
"""

from desloppify.intelligence.integrity import (
    is_holistic_subjective_finding,
    is_subjective_review_open,
    subjective_review_open_breakdown,
    unassessed_subjective_dimensions,
)
from desloppify.intelligence.review.context import ReviewContext, build_review_context
from desloppify.intelligence.review.context_holistic import build_holistic_context
from desloppify.intelligence.review.dimensions.data import load_dimensions_for_lang
from desloppify.intelligence.review.dimensions.holistic import (
    DIMENSIONS,
    DIMENSION_PROMPTS,
    REVIEW_SYSTEM_PROMPT,
    # Backward-compat aliases
    DEFAULT_DIMENSIONS,
    HOLISTIC_DIMENSION_PROMPTS,
    HOLISTIC_DIMENSIONS,
    HOLISTIC_REVIEW_SYSTEM_PROMPT,
)
from desloppify.intelligence.review.dimensions.lang import (
    HOLISTIC_DIMENSIONS_BY_LANG,
    LANG_GUIDANCE,
    get_lang_guidance,
)
from desloppify.intelligence.review.dimensions.selection import (
    resolve_dimensions,
    resolve_holistic_dimensions,
    resolve_per_file_dimensions,
)
from desloppify.intelligence.review.importing.holistic import (
    import_holistic_findings,
)
from desloppify.intelligence.review.importing.per_file import (
    import_review_findings,
)
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
from desloppify.intelligence.review.prepare_batches import build_investigation_batches
from desloppify.intelligence.review.remediation import generate_remediation_plan
from desloppify.intelligence.review.selection import (
    LOW_VALUE_NAMES,
    hash_file,
    is_low_value_file,
    select_files_for_review,
)

__all__ = [
    # dimensions — canonical names
    "DIMENSIONS",
    "DIMENSION_PROMPTS",
    "REVIEW_SYSTEM_PROMPT",
    # dimensions — backward-compat aliases
    "DEFAULT_DIMENSIONS",
    "HOLISTIC_DIMENSIONS",
    "HOLISTIC_DIMENSIONS_BY_LANG",
    "HOLISTIC_DIMENSION_PROMPTS",
    "HOLISTIC_REVIEW_SYSTEM_PROMPT",
    "LANG_GUIDANCE",
    "get_lang_guidance",
    "load_dimensions_for_lang",
    "resolve_dimensions",
    "resolve_per_file_dimensions",
    "resolve_holistic_dimensions",
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
    # import
    "import_review_findings",
    "import_holistic_findings",
    # remediation
    "generate_remediation_plan",
    # integrity
    "is_subjective_review_open",
    "is_holistic_subjective_finding",
    "subjective_review_open_breakdown",
    "unassessed_subjective_dimensions",
]
