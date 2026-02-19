"""Payload builders for show command query/output serialization."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class ShowPayloadMeta:
    total_matches: int | None = None
    hidden_by_detector: dict[str, int] | None = None
    noise_budget: int | None = None
    global_noise_budget: int | None = None


def build_show_payload(
    matches: list[dict],
    pattern: str,
    status_filter: str,
    meta: ShowPayloadMeta | None = None,
) -> dict:
    """Build the structured JSON payload shared by query file and --output."""
    resolved_meta = meta or ShowPayloadMeta()

    by_file: dict[str, list] = defaultdict(list)
    by_detector: dict[str, int] = defaultdict(int)
    by_tier: dict[int, int] = defaultdict(int)
    for finding in matches:
        by_file[finding["file"]].append(finding)
        by_detector[finding["detector"]] += 1
        by_tier[finding["tier"]] += 1

    payload = {
        "query": pattern,
        "status_filter": status_filter,
        "total": len(matches),
        "summary": {
            "by_tier": {f"T{tier}": count for tier, count in sorted(by_tier.items())},
            "by_detector": dict(sorted(by_detector.items(), key=lambda item: -item[1])),
            "files": len(by_file),
        },
        "by_file": {
            fp: [
                {
                    "id": f["id"],
                    "tier": f["tier"],
                    "confidence": f["confidence"],
                    "summary": f["summary"],
                    "detail": f.get("detail", {}),
                }
                for f in fs
            ]
            for fp, fs in sorted(by_file.items(), key=lambda x: -len(x[1]))
        },
    }
    if resolved_meta.total_matches is not None:
        payload["total_matching"] = resolved_meta.total_matches
    if resolved_meta.hidden_by_detector:
        payload["hidden"] = {
            "by_detector": resolved_meta.hidden_by_detector,
            "total": sum(resolved_meta.hidden_by_detector.values()),
        }
    if resolved_meta.noise_budget is not None:
        payload["noise_budget"] = resolved_meta.noise_budget
    if resolved_meta.global_noise_budget is not None:
        payload["noise_global_budget"] = resolved_meta.global_noise_budget
    return payload


__all__ = ["ShowPayloadMeta", "build_show_payload"]
