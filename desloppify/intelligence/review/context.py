"""Context building for review: ReviewContext, shared helpers, heuristic signals."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from desloppify.intelligence.review._context.models import ReviewContext
from desloppify.intelligence.review._context.patterns import (
    CLASS_NAME_RE,
    ERROR_PATTERNS,
    FUNC_NAME_RE,
    NAME_PREFIX_RE,
    default_review_module_patterns,
)
from desloppify.intelligence.review.context_signals.ai import gather_ai_debt_signals
from desloppify.intelligence.review.context_signals.auth import gather_auth_context
from desloppify.intelligence.review.context_signals.migration import (
    classify_error_strategy,
)
from desloppify.file_discovery import (
    disable_file_cache,
    enable_file_cache,
    is_file_cache_enabled,
    read_file_text,
    rel,
    resolve_path,
)

# ── Shared helpers ────────────────────────────────────────────────


def abs_path(filepath: str) -> str:
    """Resolve filepath to absolute using resolve_path."""
    return resolve_path(filepath)


def file_excerpt(filepath: str, max_lines: int = 30) -> str | None:
    """Read first *max_lines* of a file, returning the text or None."""
    content = read_file_text(abs_path(filepath))
    if content is None:
        return None
    lines = content.splitlines(keepends=True)
    if len(lines) <= max_lines:
        return content
    return "".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"


def dep_graph_lookup(graph: dict, filepath: str) -> dict:
    """Look up a file in the dep graph, trying absolute and relative keys."""
    resolved = resolve_path(filepath)
    entry = graph.get(resolved)
    if entry is not None:
        return entry
    # Try relative path
    rpath = rel(filepath)
    entry = graph.get(rpath)
    if entry is not None:
        return entry
    return {}


def importer_count(entry: dict) -> int:
    """Extract importer count from a dep graph entry."""
    importers = entry.get("importers", set())
    if isinstance(importers, set):
        return len(importers)
    return entry.get("importer_count", 0)


# ── Per-file review context builder ──────────────────────────────


def build_review_context(
    path: Path,
    lang,
    state: dict,
    files: list[str] | None = None,
) -> ReviewContext:
    """Gather codebase conventions for contextual evaluation.

    If *files* is provided, skip file_finder (avoids redundant filesystem walks).
    """
    if files is None:
        files = lang.file_finder(path) if lang.file_finder else []
    ctx = ReviewContext()

    if not files:
        return ctx

    already_cached = is_file_cache_enabled()
    if not already_cached:
        enable_file_cache()
    try:
        return _build_review_context_inner(files, lang, state, ctx)
    finally:
        if not already_cached:
            disable_file_cache()


def _build_review_context_inner(
    files: list[str],
    lang,
    state: dict,
    ctx: ReviewContext,
) -> ReviewContext:
    """Inner context builder (runs with file cache enabled)."""
    # Pre-read all file contents once (cache will store them)
    file_contents: dict[str, str] = {}
    for filepath in files:
        content = read_file_text(abs_path(filepath))
        if content is not None:
            file_contents[filepath] = content

    # 1. Naming vocabulary — extract function/class names, count prefixes
    prefix_counter: Counter = Counter()
    total_names = 0
    for content in file_contents.values():
        for name in FUNC_NAME_RE.findall(content) + CLASS_NAME_RE.findall(content):
            total_names += 1
            match = NAME_PREFIX_RE.match(name)
            if match:
                prefix_counter[match.group(1)] += 1
    ctx.naming_vocabulary = {
        "prefixes": dict(prefix_counter.most_common(20)),
        "total_names": total_names,
    }

    # 2. Error handling conventions — scan for patterns
    error_counts: Counter = Counter()
    for content in file_contents.values():
        for pattern_name, pattern in ERROR_PATTERNS.items():
            if pattern.search(content):
                error_counts[pattern_name] += 1
    ctx.error_conventions = dict(error_counts)

    # 3. Module patterns — what each directory typically uses
    dir_patterns: dict[str, Counter] = {}
    module_pattern_fn = getattr(lang, "review_module_patterns_fn", None)
    if not callable(module_pattern_fn):
        module_pattern_fn = default_review_module_patterns
    for filepath, content in file_contents.items():
        parts = Path(filepath).parts
        if len(parts) < 2:
            continue
        dir_name = parts[-2] + "/"
        counter = dir_patterns.setdefault(dir_name, Counter())
        pattern_names = module_pattern_fn(content)
        if not isinstance(pattern_names, list | tuple | set):
            pattern_names = default_review_module_patterns(content)
        for pattern_name in pattern_names:
            counter[pattern_name] += 1
        if re.search(r"\bclass\s+\w+", content):
            counter["class_based"] += 1
    ctx.module_patterns = {
        d: dict(c.most_common(3))
        for d, c in dir_patterns.items()
        if sum(c.values()) >= 3
    }

    # 4. Import graph summary — top files by importer count
    if lang.dep_graph:
        graph = lang.dep_graph
        importer_counts = {}
        for filepath, entry in graph.items():
            count = importer_count(entry)
            if count > 0:
                importer_counts[rel(filepath)] = count
        top = sorted(importer_counts.items(), key=lambda item: -item[1])[:20]
        ctx.import_graph_summary = {"top_imported": dict(top)}

    # 5. Zone distribution
    if lang.zone_map is not None:
        ctx.zone_distribution = lang.zone_map.counts()

    # 6. Existing findings per file (summaries only)
    findings = state.get("findings", {})
    by_file: dict[str, list[str]] = {}
    for finding in findings.values():
        if finding["status"] == "open":
            by_file.setdefault(finding["file"], []).append(
                f"{finding['detector']}: {finding['summary'][:80]}"
            )
    ctx.existing_findings = by_file

    # 7. Codebase stats
    total_files = len(file_contents)
    total_loc = sum(len(content.splitlines()) for content in file_contents.values())
    ctx.codebase_stats = {
        "total_files": total_files,
        "total_loc": total_loc,
        "avg_file_loc": total_loc // total_files if total_files else 0,
    }
    _ = (
        ctx.codebase_stats["total_files"],
        ctx.codebase_stats["total_loc"],
        ctx.codebase_stats["avg_file_loc"],
    )

    # 8. Sibling function conventions — what naming/patterns neighbors in same dir use
    dir_functions: dict[str, Counter] = {}
    for filepath, content in file_contents.items():
        parts = Path(filepath).parts
        if len(parts) < 2:
            continue
        dir_name = parts[-2] + "/"
        counter = dir_functions.setdefault(dir_name, Counter())
        for name in FUNC_NAME_RE.findall(content):
            match = NAME_PREFIX_RE.match(name)
            if match:
                counter[match.group(1)] += 1
    ctx.sibling_conventions = {
        d: dict(c.most_common(5))
        for d, c in dir_functions.items()
        if sum(c.values()) >= 3
    }

    # 9. AI debt signals
    ctx.ai_debt_signals = gather_ai_debt_signals(file_contents, rel_fn=rel)

    # 10. Auth patterns
    ctx.auth_patterns = gather_auth_context(file_contents, rel_fn=rel)

    # 11. Error strategies per file
    strategies: dict[str, str] = {}
    for filepath, content in file_contents.items():
        strategy = classify_error_strategy(content)
        if strategy:
            strategies[rel(filepath)] = strategy
    ctx.error_strategies = strategies

    return ctx


def serialize_context(ctx: ReviewContext) -> dict:
    """Convert ReviewContext to a JSON-serializable dict."""
    metrics = ("total_files", "total_loc", "avg_file_loc")
    out = {
        "naming_vocabulary": ctx.naming_vocabulary,
        "error_conventions": ctx.error_conventions,
        "module_patterns": ctx.module_patterns,
        "import_graph_summary": ctx.import_graph_summary,
        "zone_distribution": ctx.zone_distribution,
        "existing_findings": ctx.existing_findings,
        "codebase_stats": {
            key: int(ctx.codebase_stats.get(key, 0))
            for key in metrics
        },
        "sibling_conventions": ctx.sibling_conventions,
    }
    if ctx.ai_debt_signals:
        out["ai_debt_signals"] = ctx.ai_debt_signals
    if ctx.auth_patterns:
        out["auth_patterns"] = ctx.auth_patterns
    if ctx.error_strategies:
        out["error_strategies"] = ctx.error_strategies
    return out


__all__ = [
    "ReviewContext",
    "abs_path",
    "build_review_context",
    "file_excerpt",
    "dep_graph_lookup",
    "importer_count",
    "serialize_context",
]
