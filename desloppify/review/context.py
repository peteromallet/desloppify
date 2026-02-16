"""Context building for review: ReviewContext, shared helpers, heuristic signals."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .. import utils as _utils_mod
from ..utils import rel, resolve_path, read_file_text, \
    enable_file_cache, disable_file_cache


# ── ReviewContext dataclass ───────────────────────────────────────

@dataclass
class ReviewContext:
    """Codebase-wide context for contextual file evaluation."""
    naming_vocabulary: dict = field(default_factory=dict)
    error_conventions: dict = field(default_factory=dict)
    module_patterns: dict = field(default_factory=dict)
    import_graph_summary: dict = field(default_factory=dict)
    zone_distribution: dict = field(default_factory=dict)
    existing_findings: dict = field(default_factory=dict)
    codebase_stats: dict = field(default_factory=dict)
    sibling_conventions: dict = field(default_factory=dict)
    ai_debt_signals: dict = field(default_factory=dict)
    auth_patterns: dict = field(default_factory=dict)
    error_strategies: dict = field(default_factory=dict)


# ── Shared helpers ────────────────────────────────────────────────

def _abs(filepath: str) -> str:
    """Resolve filepath to absolute using resolve_path."""
    return resolve_path(filepath)


def _file_excerpt(filepath: str, max_lines: int = 30) -> str | None:
    """Read first *max_lines* of a file, returning the text or None."""
    content = read_file_text(_abs(filepath))
    if content is None:
        return None
    lines = content.splitlines(keepends=True)
    if len(lines) <= max_lines:
        return content
    return "".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"


def _dep_graph_lookup(graph: dict, filepath: str) -> dict:
    """Look up a file in the dep graph, trying absolute and relative keys."""
    abs_path = resolve_path(filepath)
    entry = graph.get(abs_path)
    if entry is not None:
        return entry
    # Try relative path
    rpath = rel(filepath)
    entry = graph.get(rpath)
    if entry is not None:
        return entry
    return {}


def _importer_count(entry: dict) -> int:
    """Extract importer count from a dep graph entry."""
    importers = entry.get("importers", set())
    if isinstance(importers, set):
        return len(importers)
    return entry.get("importer_count", 0)


# ── Regex patterns for code analysis ─────────────────────────────

_FUNC_NAME_RE = re.compile(
    r"(?:function|def|async\s+def|async\s+function)\s+(\w+)"
)
_CLASS_NAME_RE = re.compile(r"(?:class|interface|type)\s+(\w+)")

_ERROR_PATTERNS = {
    "try_catch": re.compile(r"\b(?:try\s*\{|try\s*:)"),
    "returns_null": re.compile(r"\breturn\s+(?:null|None|undefined)\b"),
    "result_type": re.compile(r"\b(?:Result|Either|Ok|Err)\b"),
    "throws": re.compile(r"\b(?:throw\s+new|raise\s+\w)"),
}

_NAME_PREFIX_RE = re.compile(
    r"^(get|set|is|has|can|should|use|create|make|build|parse|format|"
    r"validate|check|find|fetch|load|save|update|delete|remove|add|"
    r"handle|on|init|setup|render|compute|calculate|transform|convert|"
    r"to|from|with|ensure|assert|process|run|do|manage|execute)"
)

_FROM_IMPORT_RE = re.compile(
    r"^(?:from\s+\S+\s+import\s+(.+)|import\s+(.+))$", re.MULTILINE
)


def _extract_imported_names(content: str) -> set[str]:
    """Extract imported symbol names from a file's import statements."""
    names: set[str] = set()
    for m in _FROM_IMPORT_RE.finditer(content):
        raw = m.group(1) or m.group(2)
        if raw is None:
            continue
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            token = part.split()[0]
            if token.startswith("(") or token == "\\":
                continue
            token = token.strip("()")
            if token.isidentifier():
                names.add(token)
    return names


# ── Per-file review context builder ──────────────────────────────

def build_review_context(path: Path, lang, state: dict,
                         files: list[str] | None = None) -> ReviewContext:
    """Gather codebase conventions for contextual evaluation.

    If *files* is provided, skip file_finder (avoids redundant filesystem walks).
    """
    if files is None:
        files = lang.file_finder(path) if lang.file_finder else []
    ctx = ReviewContext()

    if not files:
        return ctx

    already_cached = _utils_mod._cache_enabled
    if not already_cached:
        enable_file_cache()
    try:
        return _build_review_context_inner(files, lang, state, ctx)
    finally:
        if not already_cached:
            disable_file_cache()


def _build_review_context_inner(files: list[str], lang, state: dict,
                                ctx: ReviewContext) -> ReviewContext:
    """Inner context builder (runs with file cache enabled)."""
    # Pre-read all file contents once (cache will store them)
    file_contents: dict[str, str] = {}
    for filepath in files:
        content = read_file_text(_abs(filepath))
        if content is not None:
            file_contents[filepath] = content

    # 1. Naming vocabulary — extract function/class names, count prefixes
    prefix_counter: Counter = Counter()
    total_names = 0
    for content in file_contents.values():
        for name in _FUNC_NAME_RE.findall(content) + _CLASS_NAME_RE.findall(content):
            total_names += 1
            m = _NAME_PREFIX_RE.match(name)
            if m:
                prefix_counter[m.group(1)] += 1
    ctx.naming_vocabulary = {
        "prefixes": dict(prefix_counter.most_common(20)),
        "total_names": total_names,
    }

    # 2. Error handling conventions — scan for patterns
    error_counts: Counter = Counter()
    for content in file_contents.values():
        for pattern_name, pattern in _ERROR_PATTERNS.items():
            if pattern.search(content):
                error_counts[pattern_name] += 1
    ctx.error_conventions = dict(error_counts)

    # 3. Module patterns — what each directory typically uses
    dir_patterns: dict[str, Counter] = {}
    module_pattern_fn = getattr(lang, "review_module_patterns_fn", None)
    if not callable(module_pattern_fn):
        module_pattern_fn = _default_review_module_patterns
    for filepath, content in file_contents.items():
        parts = Path(filepath).parts
        if len(parts) < 2:
            continue
        dir_name = parts[-2] + "/"
        counter = dir_patterns.setdefault(dir_name, Counter())
        pattern_names = module_pattern_fn(content)
        if not isinstance(pattern_names, (list, tuple, set)):
            pattern_names = _default_review_module_patterns(content)
        for pattern_name in pattern_names:
            counter[pattern_name] += 1
        if re.search(r"\bclass\s+\w+", content):
            counter["class_based"] += 1
    ctx.module_patterns = {
        d: dict(c.most_common(3)) for d, c in dir_patterns.items() if sum(c.values()) >= 3
    }

    # 4. Import graph summary — top files by importer count
    if lang._dep_graph:
        graph = lang._dep_graph
        importer_counts = {}
        for f, entry in graph.items():
            ic = _importer_count(entry)
            if ic > 0:
                importer_counts[rel(f)] = ic
        top = sorted(importer_counts.items(), key=lambda x: -x[1])[:20]
        ctx.import_graph_summary = {"top_imported": dict(top)}

    # 5. Zone distribution
    if lang._zone_map is not None:
        ctx.zone_distribution = lang._zone_map.counts()

    # 6. Existing findings per file (summaries only)
    findings = state.get("findings", {})
    by_file: dict[str, list[str]] = {}
    for f in findings.values():
        if f["status"] == "open":
            by_file.setdefault(f["file"], []).append(
                f"{f['detector']}: {f['summary'][:80]}"
            )
    ctx.existing_findings = by_file

    # 7. Codebase stats
    total_loc = sum(len(c.splitlines()) for c in file_contents.values())
    ctx.codebase_stats = {
        "total_files": len(file_contents),
        "total_loc": total_loc,
        "avg_file_loc": total_loc // len(file_contents) if file_contents else 0,
    }

    # 8. Sibling function conventions — what naming/patterns neighbors in same dir use
    dir_functions: dict[str, Counter] = {}
    for filepath, content in file_contents.items():
        parts = Path(filepath).parts
        if len(parts) < 2:
            continue
        dir_name = parts[-2] + "/"
        counter = dir_functions.setdefault(dir_name, Counter())
        for name in _FUNC_NAME_RE.findall(content):
            m = _NAME_PREFIX_RE.match(name)
            if m:
                counter[m.group(1)] += 1
    ctx.sibling_conventions = {
        d: dict(c.most_common(5))
        for d, c in dir_functions.items() if sum(c.values()) >= 3
    }

    # 9. AI debt signals
    ctx.ai_debt_signals = _gather_ai_debt_signals(file_contents)

    # 10. Auth patterns
    ctx.auth_patterns = _gather_auth_context(file_contents)

    # 11. Error strategies per file
    strategies: dict[str, str] = {}
    for filepath, content in file_contents.items():
        strat = _classify_error_strategy(content)
        if strat:
            strategies[rel(filepath)] = strat
    ctx.error_strategies = strategies

    return ctx


def _serialize_context(ctx: ReviewContext) -> dict:
    """Convert ReviewContext to a JSON-serializable dict."""
    d = {
        "naming_vocabulary": ctx.naming_vocabulary,
        "error_conventions": ctx.error_conventions,
        "module_patterns": ctx.module_patterns,
        "import_graph_summary": ctx.import_graph_summary,
        "zone_distribution": ctx.zone_distribution,
        "existing_findings": ctx.existing_findings,
        "codebase_stats": ctx.codebase_stats,
        "sibling_conventions": ctx.sibling_conventions,
    }
    if ctx.ai_debt_signals:
        d["ai_debt_signals"] = ctx.ai_debt_signals
    if ctx.auth_patterns:
        d["auth_patterns"] = ctx.auth_patterns
    if ctx.error_strategies:
        d["error_strategies"] = ctx.error_strategies
    return d


# ── Heuristic signal gatherers ────────────────────────────────────

_COMMENT_RE = re.compile(r"^\s*(?:#|//|/\*|\*)")
_LOG_RE = re.compile(
    r"\b(?:console\.(?:log|warn|error|debug|info)|print\(|logging\.(?:debug|info|warning|error))\b"
)
_GUARD_RE = re.compile(
    r"\b(?:if\s*\(\s*\w+\s*(?:===?\s*null|!==?\s*null|===?\s*undefined|!==?\s*undefined)"
    r"|try\s*\{|try\s*:)\b"
)
_FUNC_BODY_RE = re.compile(
    r"(?:def\s+\w+|function\s+\w+|=>\s*\{)", re.MULTILINE
)


def _gather_ai_debt_signals(file_contents: dict[str, str]) -> dict:
    """Compute per-file AI-debt heuristic signals.

    Returns ``{"file_signals": {path: {signal: value}}, "codebase_avg_comment_ratio": float}``.
    Top 20 files by signal count.
    """
    all_ratios: list[float] = []
    file_signals: dict[str, dict[str, float]] = {}

    for filepath, content in file_contents.items():
        rpath = rel(filepath)
        lines = content.splitlines()
        if not lines:
            continue

        total = len(lines)
        comment_lines = sum(1 for ln in lines if _COMMENT_RE.match(ln))
        comment_ratio = comment_lines / total

        all_ratios.append(comment_ratio)

        log_count = len(_LOG_RE.findall(content))
        func_count = len(_FUNC_BODY_RE.findall(content))
        log_density = log_count / max(func_count, 1)

        guard_count = len(_GUARD_RE.findall(content))
        guard_density = guard_count / max(func_count, 1)

        signals: dict[str, float] = {}
        if comment_ratio > 0.3:
            signals["comment_ratio"] = round(comment_ratio, 2)
        if log_density > 3.0:
            signals["log_density"] = round(log_density, 1)
        if guard_density > 2.0:
            signals["guard_density"] = round(guard_density, 1)

        if signals:
            file_signals[rpath] = signals

    # Top 20 by signal count
    top = dict(sorted(file_signals.items(), key=lambda x: -len(x[1]))[:20])
    avg_ratio = sum(all_ratios) / len(all_ratios) if all_ratios else 0.0

    return {
        "file_signals": top,
        "codebase_avg_comment_ratio": round(avg_ratio, 3),
    }


_ROUTE_AUTH_RE = re.compile(
    r"@(?:app|router|api)\.(?:get|post|put|patch|delete|route)\b"
    r"|app\.(?:get|post|put|patch|delete)\("
    r"|export\s+(?:async\s+)?function\s+(?:GET|POST|PUT|PATCH|DELETE)\b"
    r"|@router\.(?:get|post|put|patch|delete)\b",
    re.MULTILINE,
)
_AUTH_DECORATOR_RE = re.compile(
    r"@(?:login_required|require_auth|auth_required|requires_auth|authenticated)\b"
    r"|\brequireAuth\b|\bwithAuth\b|\bgetServerSession\b|\buseAuth\b"
    r"|\brequest\.user\b|\bsession\.user\b|\bgetUser\b",
)
_RLS_TABLE_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.IGNORECASE)
_RLS_ENABLE_RE = re.compile(
    r"ALTER\s+TABLE\s+(\w+)\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY"
    r"|CREATE\s+POLICY\s+\w+\s+ON\s+(\w+)",
    re.IGNORECASE,
)
_SERVICE_ROLE_RE = re.compile(r"service_role|SERVICE_ROLE|serviceRole")
_SUPABASE_CLIENT_RE = re.compile(r"\bcreateClient\b")


def _gather_auth_context(file_contents: dict[str, str]) -> dict:
    """Compute auth/RLS context from file contents.

    Returns route auth coverage, RLS coverage, service role usage, and auth patterns.
    """
    route_auth: dict[str, dict] = {}
    rls_tables: set[str] = set()
    rls_enabled: set[str] = set()
    service_role_files: list[str] = []
    auth_patterns: dict[str, int] = {}

    for filepath, content in file_contents.items():
        rpath = rel(filepath)

        # Route auth coverage
        route_matches = _ROUTE_AUTH_RE.findall(content)
        if route_matches:
            auth_matches = _AUTH_DECORATOR_RE.findall(content)
            handler_count = len(route_matches)
            auth_count = len(auth_matches)
            route_auth[rpath] = {
                "handlers": handler_count,
                "with_auth": min(auth_count, handler_count),
                "without_auth": max(0, handler_count - auth_count),
            }

        # RLS coverage (SQL/migration files)
        for m in _RLS_TABLE_RE.finditer(content):
            rls_tables.add(m.group(1))
        for m in _RLS_ENABLE_RE.finditer(content):
            table = m.group(1) or m.group(2)
            if table:
                rls_enabled.add(table)

        # Service role usage
        if _SERVICE_ROLE_RE.search(content) and _SUPABASE_CLIENT_RE.search(content):
            service_role_files.append(rpath)

        # Auth check patterns
        auth_count = len(_AUTH_DECORATOR_RE.findall(content))
        if auth_count > 0:
            auth_patterns[rpath] = auth_count

    result: dict = {}
    if route_auth:
        result["route_auth_coverage"] = route_auth
    if rls_tables:
        result["rls_coverage"] = {
            "with_rls": sorted(rls_tables & rls_enabled),
            "without_rls": sorted(rls_tables - rls_enabled),
        }
    if service_role_files:
        result["service_role_usage"] = service_role_files
    if auth_patterns:
        result["auth_patterns"] = auth_patterns
    return result


_DEPRECATED_RE = re.compile(r"@[Dd]eprecated\b|DEPRECATED", re.MULTILINE)
_MIGRATION_TODO_RE = re.compile(
    r"(?:TODO|FIXME|HACK)\b[^:\n]*\b(?:migrat|legacy|deprecat|old.?api|remove.?after)\b",
    re.IGNORECASE,
)

def _gather_migration_signals(file_contents: dict[str, str],
                              lang) -> dict:
    """Compute migration/deprecated signals from file contents.

    Returns deprecated markers, migration TODOs, pattern pairs, mixed extensions.
    """
    deprecated_files: dict[str, int] = {}
    migration_todos: list[dict] = []
    stems_by_ext: dict[str, set[str]] = {}  # stem -> set of extensions

    lang_cfg = lang
    if isinstance(lang, str):
        try:
            from ..lang import get_lang
            lang_cfg = get_lang(lang)
        except Exception:
            lang_cfg = None

    mixed_exts = set(getattr(lang_cfg, "migration_mixed_extensions", set()) or set())

    for filepath, content in file_contents.items():
        rpath = rel(filepath)

        # Deprecated markers
        dep_count = len(_DEPRECATED_RE.findall(content))
        if dep_count > 0:
            deprecated_files[rpath] = dep_count

        # Migration TODOs
        for m in _MIGRATION_TODO_RE.finditer(content):
            migration_todos.append({"file": rpath, "text": m.group(0)[:120]})

        # Track stems for mixed extension detection
        p = Path(rpath)
        stem = p.stem
        ext = p.suffix
        if ext in mixed_exts:
            stems_by_ext.setdefault(stem, set()).add(ext)

    # Pattern pair detection
    pairs = list(getattr(lang_cfg, "migration_pattern_pairs", []) or [])

    pattern_results: list[dict] = []
    for name, old_re, new_re in pairs:
        old_count = sum(1 for c in file_contents.values() if old_re.search(c))
        new_count = sum(1 for c in file_contents.values() if new_re.search(c))
        if old_count > 0 and new_count > 0:
            pattern_results.append({
                "name": name, "old_count": old_count, "new_count": new_count,
            })

    # Mixed extensions
    mixed_stems = sorted(stem for stem, exts in stems_by_ext.items()
                         if len(exts) >= 2)

    result: dict = {}
    if deprecated_files:
        result["deprecated_markers"] = {
            "total": sum(deprecated_files.values()),
            "files": deprecated_files,
        }
    if migration_todos:
        result["migration_todos"] = migration_todos[:30]
    if pattern_results:
        result["pattern_pairs"] = pattern_results
    if mixed_stems:
        result["mixed_extensions"] = mixed_stems[:20]
    return result


def _default_review_module_patterns(content: str) -> list[str]:
    """Fallback module-pattern extraction used when language hook is absent."""
    out: list[str] = []
    if re.search(r"\bexport\s+default\b", content):
        out.append("default_export")
    if re.search(r"\bexport\s+(?:function|const|class)\b", content):
        out.append("named_export")
    if re.search(r"\bdef\s+\w+", content):
        out.append("functions")
    if re.search(r"^__all__\s*=", content, re.MULTILINE):
        out.append("explicit_api")
    return out


def _classify_error_strategy(content: str) -> str | None:
    """Classify a file's primary error handling strategy."""
    throws = len(re.findall(r"\b(?:throw\s+new|raise\s+\w)", content))
    returns_null = len(re.findall(r"\breturn\s+(?:null|None|undefined)\b", content))
    result_type = len(re.findall(r"\b(?:Result|Either|Ok|Err)\b", content))
    try_catch = len(re.findall(r"\b(?:try\s*\{|try\s*:)", content))

    counts = {"throw": throws, "return_null": returns_null,
              "result_type": result_type, "try_catch": try_catch}
    total = sum(counts.values())
    if total == 0:
        return None
    dominant = max(counts, key=counts.get)  # type: ignore[arg-type]
    # "mixed" if no strategy accounts for >60% of occurrences
    if counts[dominant] / total < 0.6:
        return "mixed"
    return dominant


__all__ = [
    "ReviewContext", "build_review_context", "_serialize_context",
    "_file_excerpt", "_dep_graph_lookup", "_importer_count", "_abs",
    "_FUNC_NAME_RE", "_CLASS_NAME_RE", "_ERROR_PATTERNS",
    "_NAME_PREFIX_RE", "_FROM_IMPORT_RE",
    "_extract_imported_names",
    "_gather_ai_debt_signals", "_gather_auth_context",
    "_gather_migration_signals", "_classify_error_strategy",
]
