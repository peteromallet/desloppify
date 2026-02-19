"""Validation/parsing helpers for review dimensions payloads."""

from __future__ import annotations

_PROMPT_FIELDS = ("description", "look_for", "skip")
_PROMPT_OPTIONAL_FIELDS = ("meta",)
_MIN_SYSTEM_PROMPT_LEN = 100


def validate_payload_keys(
    payload: dict,
    *,
    required: set[str],
    context: str,
    optional: set[str] | None = None,
) -> None:
    """Validate payload has required keys and no unknown keys."""
    optional_keys = optional or set()
    allowed = set(required) | set(optional_keys)
    actual = set(payload)
    missing = sorted(required - actual)
    extra = sorted(actual - allowed)
    if missing or extra:
        raise ValueError(
            f"{context} keys invalid (missing={missing or []}, extra={extra or []})"
        )


def validate_string_list(value: object, *, context: str) -> list[str]:
    """Validate a non-empty list of non-empty strings."""
    if not isinstance(value, list) or not value:
        raise ValueError(f"{context} must be a non-empty list of strings")

    out: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{context}[{idx}] must be a non-empty string")
        out.append(item)
    return out


def validate_prompt_meta(value: object, *, context: str) -> dict[str, object]:
    """Validate optional prompt-level metadata object."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")

    validate_payload_keys(
        value,
        required=set(),
        optional={"enabled_by_default", "display_name", "weight", "reset_on_scan"},
        context=context,
    )

    out: dict[str, object] = {}

    enabled = value.get("enabled_by_default")
    if enabled is not None:
        if not isinstance(enabled, bool):
            raise ValueError(f"{context}.enabled_by_default must be a boolean")
        out["enabled_by_default"] = enabled

    display_name = value.get("display_name")
    if display_name is not None:
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError(f"{context}.display_name must be a non-empty string")
        out["display_name"] = display_name.strip()

    weight = value.get("weight")
    if weight is not None:
        if isinstance(weight, bool) or not isinstance(weight, int | float):
            raise ValueError(f"{context}.weight must be a number")
        if float(weight) < 0:
            raise ValueError(f"{context}.weight must be >= 0")
        out["weight"] = float(weight)

    reset_on_scan = value.get("reset_on_scan")
    if reset_on_scan is not None:
        if not isinstance(reset_on_scan, bool):
            raise ValueError(f"{context}.reset_on_scan must be a boolean")
        out["reset_on_scan"] = reset_on_scan

    return out


def validate_dimension_prompts(
    value: object, *, context: str
) -> dict[str, dict[str, object]]:
    """Validate the dimension prompt map schema."""
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{context} must be a non-empty object")

    out: dict[str, dict[str, object]] = {}
    for dim_name, entry in value.items():
        if not isinstance(dim_name, str) or not dim_name.strip():
            raise ValueError(
                f"{context} contains an invalid dimension name: {dim_name!r}"
            )
        if not isinstance(entry, dict):
            raise ValueError(f"{context}.{dim_name} must be an object")

        validate_payload_keys(
            entry,
            required=set(_PROMPT_FIELDS),
            optional=set(_PROMPT_OPTIONAL_FIELDS),
            context=f"{context}.{dim_name}",
        )

        description = entry.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(
                f"{context}.{dim_name}.description must be a non-empty string"
            )

        parsed_entry: dict[str, object] = {
            "description": description,
            "look_for": validate_string_list(
                entry.get("look_for"),
                context=f"{context}.{dim_name}.look_for",
            ),
            "skip": validate_string_list(
                entry.get("skip"),
                context=f"{context}.{dim_name}.skip",
            ),
        }
        meta = validate_prompt_meta(entry.get("meta"), context=f"{context}.{dim_name}.meta")
        if meta:
            parsed_entry["meta"] = meta
        out[dim_name] = parsed_entry
    return out


def validate_dimensions_list(value: object, *, context: str) -> list[str]:
    """Validate dimension names list."""
    dims = validate_string_list(value, context=context)
    seen: set[str] = set()
    duplicates: list[str] = []
    for dim in dims:
        if dim in seen:
            duplicates.append(dim)
        seen.add(dim)
    if duplicates:
        raise ValueError(
            f"{context} contains duplicate entries: {sorted(set(duplicates))}"
        )
    return dims


def validate_system_prompt(value: object, *, context: str) -> str:
    """Validate non-trivial system prompt text."""
    if not isinstance(value, str) or len(value.strip()) < _MIN_SYSTEM_PROMPT_LEN:
        raise ValueError(
            f"{context} must be a non-empty string with at least {_MIN_SYSTEM_PROMPT_LEN} chars"
        )
    return value


def parse_dimensions_payload(
    payload: dict,
    *,
    context_prefix: str,
) -> tuple[list[str], dict[str, dict[str, object]], str]:
    """Validate and parse a unified review dimensions payload."""
    dims_key = "default_dimensions"
    validate_payload_keys(
        payload,
        required={"dimension_prompts", "system_prompt"},
        optional={"default_dimensions"},
        context=context_prefix,
    )

    dims: list[str] = []
    if dims_key in payload:
        dims = validate_dimensions_list(
            payload.get(dims_key),
            context=f"{context_prefix}.{dims_key}",
        )
    prompts = validate_dimension_prompts(
        payload.get("dimension_prompts"),
        context=f"{context_prefix}.dimension_prompts",
    )
    system_prompt = validate_system_prompt(
        payload.get("system_prompt"),
        context=f"{context_prefix}.system_prompt",
    )

    for dim_name, entry in prompts.items():
        meta = entry.get("meta")
        if isinstance(meta, dict) and meta.get("enabled_by_default") is True:
            if dim_name not in dims:
                dims.append(dim_name)

    if not dims:
        raise ValueError(
            f"{context_prefix} must define at least one default dimension "
            "(either via default_dimensions or dimension_prompts.*.meta.enabled_by_default)"
        )

    missing = [dim for dim in dims if dim not in prompts]
    if missing:
        raise ValueError(
            f"{context_prefix}.{dims_key} missing prompts: {sorted(missing)}"
        )

    return dims, prompts, system_prompt


__all__ = [
    "parse_dimensions_payload",
    "validate_dimension_prompts",
    "validate_prompt_meta",
    "validate_dimensions_list",
    "validate_payload_keys",
    "validate_string_list",
    "validate_system_prompt",
]
