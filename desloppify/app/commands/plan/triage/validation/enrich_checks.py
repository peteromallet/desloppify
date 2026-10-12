"""Enrichment and cluster-level validation helpers for triage stages."""

from __future__ import annotations

import re
from pathlib import Path

from desloppify.base.output.terminal import colorize

from ..review_coverage import cluster_issue_ids
from .stage_policy import require_prerequisite

_PATH_RE = re.compile(r"(?:[\w./-]+/)?(?:src|supabase)/[\w./-]+\.\w+(?::\d+(?:[-:]\d+)?)?")
_LINE_SUFFIX_RE = re.compile(r":\d+(?:[-:]\d+)?$")
_EXT_SWAPS = {".ts": ".tsx", ".tsx": ".ts", ".js": ".jsx", ".jsx": ".js"}
_VALID_EFFORTS = {"trivial", "small", "medium", "large"}


def _strip_line_suffix(path_str: str) -> str:
    """Remove trailing :N, :N-M, :N:M line-number suffixes from a path."""
    return _LINE_SUFFIX_RE.sub("", path_str)


def _manual_clusters_with_issues(plan: dict):
    """Yield manual clusters that still carry issue IDs."""
    for name, cluster in plan.get("clusters", {}).items():
        if cluster.get("auto") or not cluster_issue_ids(cluster):
            continue
        yield name, cluster


def _cluster_steps(cluster: dict) -> list[dict]:
    """Return structured action steps for one cluster."""
    return [
        step
        for step in (cluster.get("action_steps") or [])
        if isinstance(step, dict)
    ]


def _detail_paths(detail: str) -> list[str]:
    """Extract file paths from one step detail string."""
    if not detail:
        return []
    return _PATH_RE.findall(detail)


def _path_exists_or_alt_exists(repo_root: Path, path_str: str) -> bool:
    """Return whether the referenced path or a ts/js sibling exists."""
    cleaned = _strip_line_suffix(path_str)
    path = repo_root / cleaned
    if path.exists():
        return True
    alt_ext = _EXT_SWAPS.get(path.suffix)
    return bool(alt_ext and path.with_suffix(alt_ext).exists())


def _require_organize_stage_for_enrich(stages: dict) -> bool:
    """Gate: organize must be done before enrich."""
    return require_prerequisite(
        stages,
        flow="enrich",
        messages={
            "observe": (
                "  Cannot enrich: observe stage not complete.",
                '  Run: desloppify plan triage --stage observe --report "..."',
            ),
            "reflect": (
                "  Cannot enrich: reflect stage not complete.",
                '  Run: desloppify plan triage --stage reflect --report "..."',
            ),
            "organize": (
                "  Cannot enrich: organize stage not complete.",
                '  Run: desloppify plan triage --stage organize --report "..."',
            ),
        },
    )


def _underspecified_steps(plan: dict) -> list[tuple[str, int, int]]:
    """Return (cluster_name, bare_count, total_count) for steps missing detail or issue_refs."""
    results: list[tuple[str, int, int]] = []
    for name, cluster in _manual_clusters_with_issues(plan):
        steps = _cluster_steps(cluster)
        if not steps:
            continue
        bare = sum(
            1
            for step in steps
            if isinstance(step, dict) and (not step.get("detail") or not step.get("issue_refs"))
        )
        if bare > 0:
            results.append((name, bare, len(steps)))
    return results


def _steps_with_bad_paths(plan: dict, repo_root: Path) -> list[tuple[str, int, list[str]]]:
    """Return steps referencing file paths that don't exist on disk."""
    results: list[tuple[str, int, list[str]]] = []
    for name, cluster in _manual_clusters_with_issues(plan):
        for i, step in enumerate(_cluster_steps(cluster)):
            detail = step.get("detail", "")
            if not detail:
                continue
            bad = [
                path_str
                for path_str in _detail_paths(detail)
                if not _path_exists_or_alt_exists(repo_root, path_str)
            ]
            if bad:
                results.append((name, i + 1, bad))
    return results


def _steps_without_effort(plan: dict) -> list[tuple[str, int, int]]:
    """Return (cluster_name, missing_count, total) for steps without effort tags."""
    results: list[tuple[str, int, int]] = []
    for name, cluster in _manual_clusters_with_issues(plan):
        steps = _cluster_steps(cluster)
        if not steps:
            continue
        missing = sum(
            1 for step in steps if isinstance(step, dict) and step.get("effort") not in _VALID_EFFORTS
        )
        if missing:
            results.append((name, missing, len(steps)))
    return results


def _cluster_file_overlaps(plan: dict) -> list[tuple[str, str, list[str]]]:
    """Return pairs of clusters with overlapping file references in step details."""
    cluster_files: dict[str, set[str]] = {}
    for name, cluster in _manual_clusters_with_issues(plan):
        paths: set[str] = set()
        for step in _cluster_steps(cluster):
            paths.update(_detail_paths(step.get("detail", "")))
        if paths:
            cluster_files[name] = paths

    overlaps: list[tuple[str, str, list[str]]] = []
    names = sorted(cluster_files.keys())
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            shared = cluster_files[left] & cluster_files[right]
            if shared:
                overlaps.append((left, right, sorted(shared)))
    return overlaps


def _clusters_with_directory_scatter(
    plan: dict,
    *,
    threshold: int = 5,
) -> list[tuple[str, int, list[str]]]:
    """Return clusters whose issues span too many unrelated directories."""
    results: list[tuple[str, int, list[str]]] = []
    for name, cluster in _manual_clusters_with_issues(plan):
        dirs: set[str] = set()
        for step in _cluster_steps(cluster):
            for path_str in _detail_paths(step.get("detail", "")):
                parts = path_str.split("/")
                if len(parts) >= 3:
                    dirs.add("/".join(parts[:3]))
                elif len(parts) >= 2:
                    dirs.add("/".join(parts[:2]))
        if len(dirs) >= threshold:
            results.append((name, len(dirs), sorted(dirs)[:6]))
    return results


def _clusters_with_high_step_ratio(
    plan: dict,
    *,
    max_ratio: float = 1.0,
) -> list[tuple[str, int, int, float]]:
    """Return clusters where step count exceeds issue count."""
    results: list[tuple[str, int, int, float]] = []
    for name, cluster in _manual_clusters_with_issues(plan):
        steps = len(_cluster_steps(cluster))
        issues = len(cluster_issue_ids(cluster))
        if issues >= 3 and steps > 0:
            ratio = steps / issues
            if ratio > max_ratio:
                results.append((name, steps, issues, ratio))
    return results


def _steps_missing_issue_refs(plan: dict) -> list[tuple[str, int, int]]:
    """Return (cluster_name, missing_count, total) for steps without issue_refs."""
    results: list[tuple[str, int, int]] = []
    for name, cluster in _manual_clusters_with_issues(plan):
        steps = _cluster_steps(cluster)
        if not steps:
            continue
        missing = sum(1 for step in steps if not step.get("issue_refs"))
        if missing:
            results.append((name, missing, len(steps)))
    return results


def _steps_with_vague_detail(plan: dict, repo_root: Path) -> list[tuple[str, int, str]]:
    """Return steps with detail too vague to be executor-ready."""
    del repo_root
    results: list[tuple[str, int, str]] = []
    for name, cluster in _manual_clusters_with_issues(plan):
        for i, step in enumerate(_cluster_steps(cluster)):
            detail = step.get("detail", "")
            if not detail:
                results.append((name, i + 1, step.get("title", "(no title)")))
                continue
            has_path = bool(_detail_paths(detail))
            if len(detail) < 80 and not has_path:
                results.append((name, i + 1, step.get("title", "(no title)")))
    return results


def _steps_referencing_skipped_issues(plan: dict) -> list[tuple[str, int, list[str]]]:
    """Return steps whose issue_refs include wontfixed/skipped issues."""
    wontfixed = set()
    for fid, issue in plan.get("issues", {}).items():
        if isinstance(issue, dict) and issue.get("status") in ("wontfix", "skipped"):
            wontfixed.add(fid)
    for fid in plan.get("wontfix", {}):
        wontfixed.add(fid)

    if not wontfixed:
        return []

    results: list[tuple[str, int, list[str]]] = []
    for name, cluster in _manual_clusters_with_issues(plan):
        for i, step in enumerate(_cluster_steps(cluster)):
            refs = step.get("issue_refs") or []
            stale = [ref for ref in refs if ref in wontfixed]
            if stale:
                results.append((name, i + 1, stale))
    return results


def _enrich_report_or_error(report: str | None) -> str | None:
    if not report:
        print(colorize("  --report is required for --stage enrich.", "red"))
        print(colorize("  Summarize the enrichment work you did:", "dim"))
        print(colorize("  - Which clusters did you add detail/refs to?", "dim"))
        print(colorize("  - Are steps specific enough for an executor with zero context?", "dim"))
        print(colorize("  - Did you link issue_refs so steps auto-complete on resolve?", "dim"))
        return None
    if len(report) < 100:
        print(colorize(f"  Report too short: {len(report)} chars (minimum 100).", "red"))
        print(colorize("  Explain what enrichment you did and why steps are executor-ready.", "dim"))
        return None
    return report


__all__ = [
    "_cluster_file_overlaps",
    "_clusters_with_directory_scatter",
    "_clusters_with_high_step_ratio",
    "_enrich_report_or_error",
    "_require_organize_stage_for_enrich",
    "_steps_missing_issue_refs",
    "_steps_referencing_skipped_issues",
    "_steps_with_bad_paths",
    "_steps_with_vague_detail",
    "_steps_without_effort",
    "_strip_line_suffix",
    "_underspecified_steps",
]
