"""Load and validate review dimension payloads from JSON data files."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

from desloppify.intelligence.review.feedback_contract import ensure_prompt_contract
from desloppify.intelligence.review.dimensions.validation import (
    parse_dimensions_payload,
)

_LANG_DIR = Path(__file__).resolve().parents[3] / "languages"
_LANG_DATA_SUBDIR = "review_data"
_DATA_DIR = _LANG_DIR / "_framework" / _LANG_DATA_SUBDIR

# Canonical filename for the unified dimensions payload.
_DIMENSIONS_FILE = "dimensions.json"


def _load_json_payload_from_path(path: Path) -> dict:
    """Load a JSON payload from *path* and return a dict."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Unable to read dimensions payload: {path}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in dimensions payload: {path}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"Dimensions payload must be a JSON object: {path}")
    return payload


def _lang_payload_path(lang_name: str, filename: str) -> Path:
    """Resolve the per-language review payload path."""
    return _LANG_DIR / lang_name / _LANG_DATA_SUBDIR / filename


def _override_filename(filename: str) -> str:
    """Convert ``foo.json`` to ``foo.override.json``."""
    if not filename.endswith(".json"):
        return f"{filename}.override.json"
    return f"{filename[:-5]}.override.json"


def _load_json_payload(filename: str) -> dict:
    """Load a JSON payload from the shared language review-data directory."""
    return _load_json_payload_from_path(_DATA_DIR / filename)


def _validate_optional_string_list(value: object, *, context: str) -> list[str]:
    """Validate an optional list of strings (empty allowed)."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list of strings")
    out: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{context}[{idx}] must be a non-empty string")
        out.append(item)
    return out


def _apply_dimensions_override(
    base_payload: dict,
    override_payload: dict,
    *,
    dims_key: str,
    context: str,
) -> dict:
    """Apply a language override payload to a base dimensions payload."""
    if not isinstance(override_payload, dict):
        raise ValueError(f"{context} must be a JSON object")

    allowed = {
        dims_key,
        f"{dims_key}_append",
        f"{dims_key}_remove",
        "dimension_prompts",
        "dimension_prompts_remove",
        "system_prompt",
        "system_prompt_append",
    }
    actual = set(override_payload)
    extra = sorted(actual - allowed)
    if extra:
        raise ValueError(f"{context} has unsupported keys: {extra}")

    out = copy.deepcopy(base_payload)

    if dims_key in override_payload:
        out[dims_key] = override_payload[dims_key]

    dims = list(out.get(dims_key, []))
    for dim in _validate_optional_string_list(
        override_payload.get(f"{dims_key}_append"),
        context=f"{context}.{dims_key}_append",
    ):
        if dim not in dims:
            dims.append(dim)

    remove_dims = set(
        _validate_optional_string_list(
            override_payload.get(f"{dims_key}_remove"),
            context=f"{context}.{dims_key}_remove",
        )
    )
    if remove_dims:
        dims = [dim for dim in dims if dim not in remove_dims]
    out[dims_key] = dims

    if "dimension_prompts" in override_payload:
        prompt_overrides = override_payload["dimension_prompts"]
        if not isinstance(prompt_overrides, dict):
            raise ValueError(f"{context}.dimension_prompts must be an object")
        prompts = dict(out.get("dimension_prompts", {}))
        for dim_name, prompt in prompt_overrides.items():
            prompts[dim_name] = prompt
        out["dimension_prompts"] = prompts

    remove_prompts = _validate_optional_string_list(
        override_payload.get("dimension_prompts_remove"),
        context=f"{context}.dimension_prompts_remove",
    )
    if remove_prompts:
        prompts = dict(out.get("dimension_prompts", {}))
        for dim_name in remove_prompts:
            prompts.pop(dim_name, None)
        out["dimension_prompts"] = prompts

    if "system_prompt" in override_payload:
        out["system_prompt"] = override_payload["system_prompt"]
    if "system_prompt_append" in override_payload:
        suffix = override_payload["system_prompt_append"]
        if not isinstance(suffix, str):
            raise ValueError(f"{context}.system_prompt_append must be a string")
        current = out.get("system_prompt", "")
        sep = "\n\n" if current and suffix else ""
        out["system_prompt"] = f"{current}{sep}{suffix}"

    return out


def _load_payload_for_lang(
    lang_name: str,
    filename: str,
    *,
    dims_key: str,
) -> tuple[dict, str]:
    """Load payload for a language using shared-base + optional language overlay.

    Resolution order:
    1) Start from shared base payload in ``lang/framework/review_data``.
    2) If language override payload exists, patch the selected base.
    """
    base_payload = _load_json_payload(filename)
    context = filename

    lang_override_path = _lang_payload_path(lang_name, _override_filename(filename))
    if lang_override_path.is_file():
        override_payload = _load_json_payload_from_path(lang_override_path)
        base_payload = _apply_dimensions_override(
            base_payload,
            override_payload,
            dims_key=dims_key,
            context=str(lang_override_path),
        )
        context = f"{context} + {lang_override_path}"

    return base_payload, context


# ---------------------------------------------------------------------------
# Canonical loaders — use these for new code.
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_dimensions() -> tuple[list[str], dict[str, dict[str, object]], str]:
    """Load and validate the unified review dimension definitions."""
    payload = _load_json_payload(_DIMENSIONS_FILE)
    dims, prompts, system_prompt = parse_dimensions_payload(
        payload, context_prefix=_DIMENSIONS_FILE
    )
    return dims, prompts, ensure_prompt_contract(system_prompt)


@lru_cache(maxsize=16)
def load_dimensions_for_lang(
    lang_name: str,
) -> tuple[list[str], dict[str, dict[str, object]], str]:
    """Load unified review dimensions for a language (with lang override applied)."""
    payload, context = _load_payload_for_lang(
        lang_name,
        _DIMENSIONS_FILE,
        dims_key="default_dimensions",
    )
    dims, prompts, system_prompt = parse_dimensions_payload(
        payload, context_prefix=context
    )
    return dims, prompts, ensure_prompt_contract(system_prompt)
