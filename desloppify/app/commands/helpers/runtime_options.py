"""Language runtime-option parsing helpers."""

from __future__ import annotations

import sys

from desloppify.utils import colorize


def parse_lang_opt_assignments(raw_values: list[str] | None) -> dict[str, str]:
    """Parse repeated KEY=VALUE --lang-opt inputs."""
    values = raw_values or []
    parsed: dict[str, str] = {}
    for raw in values:
        text = (raw or "").strip()
        if not text:
            continue
        if "=" not in text:
            raise ValueError(f"Invalid --lang-opt '{raw}'. Expected KEY=VALUE.")
        key, value = text.split("=", 1)
        key = key.strip().replace("-", "_")
        if not key:
            raise ValueError(f"Invalid --lang-opt '{raw}'. Missing option key.")
        parsed[key] = value.strip()
    return parsed


def resolve_lang_runtime_options(args, lang) -> dict[str, object]:
    """Resolve runtime options from generic --lang-opt inputs."""
    try:
        options = parse_lang_opt_assignments(getattr(args, "lang_opt", None))
    except ValueError as exc:
        print(colorize(f"  {exc}", "red"), file=sys.stderr)
        sys.exit(2)

    try:
        return lang.normalize_runtime_options(options, strict=True)
    except KeyError as exc:
        supported = sorted((lang.runtime_option_specs or {}).keys())
        hint = ", ".join(supported) if supported else "(none)"
        print(colorize(f"  {exc}", "red"), file=sys.stderr)
        print(
            colorize(f"  Supported {lang.name} runtime options: {hint}", "dim"),
            file=sys.stderr,
        )
        sys.exit(2)


__all__ = ["parse_lang_opt_assignments", "resolve_lang_runtime_options"]
