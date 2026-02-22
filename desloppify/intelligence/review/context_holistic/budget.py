"""Sizing and truncation helpers for holistic context payloads."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from desloppify.intelligence.review.context import file_excerpt
from desloppify.file_discovery import rel

_DEF_SIGNATURE_RE = re.compile(
    r"(?:^|\n)\s*(?:async\s+def|def|async\s+function|function)\s+\w+\s*\(([^)]*)\)",
    re.MULTILINE,
)
_PY_PASSTHROUGH_RE = re.compile(
    r"\bdef\s+(\w+)\s*\([^)]*\)\s*:\s*(?:\n\s*(?:#.*)?\s*)*\n?\s*return\s+(\w+)\s*\(",
    re.MULTILINE,
)
_TS_PASSTHROUGH_RE = re.compile(
    r"\bfunction\s+(\w+)\s*\([^)]*\)\s*\{\s*return\s+(\w+)\s*\(",
    re.MULTILINE,
)
_INTERFACE_RE = re.compile(
    r"\binterface\s+([A-Za-z_]\w*)\b|\bclass\s+([A-Za-z_]\w*Protocol)\b"
)
_IMPLEMENTS_RE = re.compile(r"\bclass\s+\w+\s+implements\s+([^{:\n]+)")
_INHERITS_RE = re.compile(r"\bclass\s+\w+\s*(?:\(([^)\n]+)\)\s*:|:\s*([^\n{]+))")
_CHAIN_RE = re.compile(r"\b(?:\w+\.){2,}\w+\b")
_CONFIG_BAG_RE = re.compile(
    r"\b(?:config|configs|options|opts|params|ctx|context)\b",
    re.IGNORECASE,
)


def _count_signature_params(params_blob: str) -> int:
    """Best-effort parameter counting for function signatures."""
    cleaned = params_blob.strip()
    if not cleaned:
        return 0
    parts = [part.strip() for part in cleaned.split(",") if part.strip()]
    filtered = [part for part in parts if part not in {"self", "cls", "this"}]
    return len(filtered)


def _extract_type_names(blob: str) -> list[str]:
    """Extract candidate type names from implements/inherits blobs."""
    names: list[str] = []
    for raw in re.split(r"[,\s()]+", blob):
        token = raw.strip()
        if not token:
            continue
        token = token.split(".")[-1]
        token = token.split("<")[0]
        token = token.strip(":")
        if not token or not re.match(r"^[A-Za-z_]\w*$", token):
            continue
        names.append(token)
    return names


def _score_clamped(raw: float) -> int:
    """Clamp score-like values to [0, 100]."""
    return int(max(0, min(100, round(raw))))


def _abstractions_context(file_contents: dict[str, str]) -> dict:
    util_files = []
    wrappers_by_file: list[dict[str, object]] = []
    interface_declarations: dict[str, set[str]] = defaultdict(set)
    implementations: dict[str, set[str]] = defaultdict(set)
    indirection_hotspots: list[dict[str, object]] = []
    wide_param_bags: list[dict[str, object]] = []

    total_function_signatures = 0
    total_wrappers = 0

    for filepath, content in file_contents.items():
        rpath = rel(filepath)
        basename = Path(rpath).stem.lower()
        if basename in {"utils", "helpers", "util", "helper", "common", "misc"}:
            util_files.append(
                {
                    "file": rpath,
                    "loc": len(content.splitlines()),
                    "excerpt": file_excerpt(filepath) or "",
                }
            )

        signatures = _DEF_SIGNATURE_RE.findall(content)
        total_function_signatures += len(signatures)

        py_wrappers = [
            (wrapper, target)
            for wrapper, target in _PY_PASSTHROUGH_RE.findall(content)
            if wrapper != target
        ]
        ts_wrappers = [
            (wrapper, target)
            for wrapper, target in _TS_PASSTHROUGH_RE.findall(content)
            if wrapper != target
        ]
        wrapper_pairs = py_wrappers + ts_wrappers
        if wrapper_pairs:
            total_wrappers += len(wrapper_pairs)
            wrappers_by_file.append(
                {
                    "file": rpath,
                    "count": len(wrapper_pairs),
                    "samples": [f"{w}->{t}" for w, t in wrapper_pairs[:5]],
                }
            )

        for match in _INTERFACE_RE.finditer(content):
            iface = match.group(1) or match.group(2)
            if iface:
                interface_declarations[iface].add(rpath)

        for match in _IMPLEMENTS_RE.finditer(content):
            for iface in _extract_type_names(match.group(1)):
                implementations[iface].add(rpath)
        for match in _INHERITS_RE.finditer(content):
            blob = match.group(1) or match.group(2) or ""
            for iface in _extract_type_names(blob):
                implementations[iface].add(rpath)

        chain_matches = _CHAIN_RE.findall(content)
        max_chain_depth = max((token.count(".") for token in chain_matches), default=0)
        if max_chain_depth >= 3 or len(chain_matches) >= 6:
            indirection_hotspots.append(
                {
                    "file": rpath,
                    "max_chain_depth": max_chain_depth,
                    "chain_count": len(chain_matches),
                }
            )

        wide_functions = sum(
            1 for params_blob in signatures if _count_signature_params(params_blob) >= 7
        )
        bag_mentions = len(_CONFIG_BAG_RE.findall(content))
        if wide_functions > 0 or bag_mentions >= 10:
            wide_param_bags.append(
                {
                    "file": rpath,
                    "wide_functions": wide_functions,
                    "config_bag_mentions": bag_mentions,
                }
            )

    one_impl_interfaces: list[dict[str, object]] = []
    for iface, declared_in in interface_declarations.items():
        implemented_in = sorted(implementations.get(iface, set()))
        if len(implemented_in) != 1:
            continue
        one_impl_interfaces.append(
            {
                "interface": iface,
                "declared_in": sorted(declared_in),
                "implemented_in": implemented_in,
            }
        )

    wrappers_by_file.sort(key=lambda item: -int(item["count"]))
    indirection_hotspots.sort(
        key=lambda item: (-int(item["max_chain_depth"]), -int(item["chain_count"]))
    )
    wide_param_bags.sort(
        key=lambda item: (
            -int(item["wide_functions"]),
            -int(item["config_bag_mentions"]),
        )
    )
    one_impl_interfaces.sort(key=lambda item: str(item["interface"]))

    wrapper_rate = total_wrappers / max(total_function_signatures, 1)
    abstraction_leverage = _score_clamped(
        100 - (wrapper_rate * 120) - (len(util_files) * 1.5)
    )
    indirection_cost = _score_clamped(
        100
        - (sum(item["max_chain_depth"] for item in indirection_hotspots[:20]) * 2.5)
        - (sum(item["wide_functions"] for item in wide_param_bags[:20]) * 2.0)
    )
    interface_honesty = _score_clamped(100 - (len(one_impl_interfaces) * 8))

    util_files = sorted(util_files, key=lambda item: -item["loc"])[:20]
    context: dict[str, object] = {
        "util_files": util_files,
        "summary": {
            "wrapper_rate": round(wrapper_rate, 3),
            "total_wrappers": total_wrappers,
            "total_function_signatures": total_function_signatures,
            "one_impl_interface_count": len(one_impl_interfaces),
            "indirection_hotspot_count": len(indirection_hotspots),
            "wide_param_bag_count": len(wide_param_bags),
        },
        "sub_axes": {
            "abstraction_leverage": abstraction_leverage,
            "indirection_cost": indirection_cost,
            "interface_honesty": interface_honesty,
        },
    }
    if wrappers_by_file:
        context["pass_through_wrappers"] = wrappers_by_file[:20]
    if one_impl_interfaces:
        context["one_impl_interfaces"] = one_impl_interfaces[:20]
    if indirection_hotspots:
        context["indirection_hotspots"] = indirection_hotspots[:20]
    if wide_param_bags:
        context["wide_param_bags"] = wide_param_bags[:20]
    return context


def _codebase_stats(file_contents: dict[str, str]) -> dict[str, int]:
    total_loc = sum(len(content.splitlines()) for content in file_contents.values())
    return {
        "total_files": len(file_contents),
        "total_loc": total_loc,
    }
