"""Test coverage gap detection — static analysis of test file mapping and quality.

Measures test *need* (what's dangerous without tests) not just test existence,
weighting by blast radius (importer count) so that testing one critical file
moves the score more than testing ten trivial ones.
"""

from __future__ import annotations

import logging
import math
import os
import re
from pathlib import Path

from .lang_hooks import load_lang_hook_module
from ..utils import PROJECT_ROOT
from ..zones import FileZoneMap, Zone

# Minimum LOC threshold — tiny files don't need dedicated tests
_MIN_LOC = 10

# Max untested modules to report when there are zero tests
_MAX_NO_TESTS_ENTRIES = 50
LOGGER = logging.getLogger(__name__)

def detect_test_coverage(
    graph: dict,
    zone_map: FileZoneMap,
    lang_name: str,
    extra_test_files: set[str] | None = None,
    complexity_map: dict[str, float] | None = None,
) -> tuple[list[dict], int]:
    """Detect test coverage gaps.

    Args:
        graph: dep graph from lang.build_dep_graph — {filepath: {"imports": set, "importer_count": int, ...}}
        zone_map: FileZoneMap from lang._zone_map
        lang_name: language plugin name (for loading language-specific coverage hooks)
        extra_test_files: test files outside the scanned path (e.g. PROJECT_ROOT/tests/)
        complexity_map: {filepath: complexity_score} from structural phase — files above
            _COMPLEXITY_TIER_UPGRADE threshold get their tier upgraded to 2

    Returns:
        (entries, potential) where entries are finding-like dicts and potential
        is LOC-weighted (sqrt(loc) capped at 50 per file).
    """
    # Normalize graph paths to relative (zone_map uses relative paths, graph may use absolute)
    root_prefix = str(PROJECT_ROOT) + os.sep
    def _to_rel(p: str) -> str:
        return p[len(root_prefix):] if p.startswith(root_prefix) else p

    needs_norm = any(k.startswith(root_prefix) for k in list(graph)[:3])
    if needs_norm:
        norm_graph: dict = {}
        for k, v in graph.items():
            rk = _to_rel(k)
            norm_graph[rk] = {
                **v,
                "imports": {_to_rel(imp) for imp in v.get("imports", set())},
            }
        graph = norm_graph

    all_files = zone_map.all_files()
    production_files = set(zone_map.include_only(all_files, Zone.PRODUCTION, Zone.SCRIPT))
    test_files = set(zone_map.include_only(all_files, Zone.TEST))

    # Include test files from outside the scanned path (normalize to relative)
    if extra_test_files:
        test_files |= {_to_rel(f) for f in extra_test_files}

    # Only score production files that are substantial and have testable logic.
    # Excludes type-only files, barrel re-exports, and declaration-only files.
    scorable = {f for f in production_files
                if _file_loc(f) >= _MIN_LOC and _has_testable_logic(f, lang_name)}

    if not scorable:
        return [], 0

    # LOC-weighted potential: sqrt(loc) capped at 50 per file.
    # This weights large untested files more heavily — a 500-LOC untested file
    # contributes ~22x more to score impact than a 15-LOC file.
    potential = round(sum(min(math.sqrt(_file_loc(f)), 50) for f in scorable))

    # If zero test files, emit findings for top modules by LOC
    if not test_files:
        entries = _no_tests_findings(scorable, graph, lang_name, complexity_map)
        return entries, potential

    # Step 1: Import-based mapping (precise)
    directly_tested = _import_based_mapping(graph, test_files, production_files, lang_name)

    # Step 2: Naming convention fallback
    name_tested = _naming_based_mapping(test_files, production_files, lang_name)
    directly_tested |= name_tested

    # Step 3: Transitive coverage via BFS
    transitively_tested = _transitive_coverage(directly_tested, graph, production_files)

    # Step 4: Test quality analysis
    test_quality = _analyze_test_quality(test_files, lang_name)

    # Step 5: Generate findings
    entries = _generate_findings(
        scorable, directly_tested, transitively_tested,
        test_quality, graph, lang_name,
        complexity_map=complexity_map,
    )

    return entries, potential


# ── Internal helpers ──────────────────────────────────────


def _file_loc(filepath: str) -> int:
    """Count lines in a file, returning 0 on error."""
    try:
        return len(Path(filepath).read_text().splitlines())
    except (OSError, UnicodeDecodeError):
        return 0


def _loc_weight(loc: int) -> float:
    """Compute LOC weight for a file: sqrt(loc) capped at 50."""
    return min(math.sqrt(loc), 50)


def _has_testable_logic(filepath: str, lang_name: str) -> bool:
    """Check whether a file contains runtime logic worth testing.

    Returns False for files that need no dedicated tests:
    - .d.ts type definition files (TypeScript)
    - Files containing only type/interface declarations and imports
    - Barrel files containing only re-exports
    - Python files with no function or method definitions
    """
    try:
        content = Path(filepath).read_text()
    except (OSError, UnicodeDecodeError):
        return True  # assume testable if unreadable

    mod = _load_lang_test_coverage_module(lang_name)
    has_logic = getattr(mod, "has_testable_logic", None)
    if callable(has_logic):
        return bool(has_logic(filepath, content))
    return True


def _load_lang_test_coverage_module(lang_name: str):
    """Load language-specific test coverage helpers from ``lang/<name>/test_coverage.py``."""
    return load_lang_hook_module(lang_name, "test_coverage") or object()


def _is_runtime_entrypoint(filepath: str, lang_name: str) -> bool:
    """Return True when language hook marks a file as runtime entrypoint."""
    try:
        content = Path(filepath).read_text()
    except (OSError, UnicodeDecodeError):
        return False
    mod = _load_lang_test_coverage_module(lang_name)
    detector = getattr(mod, "is_runtime_entrypoint", None)
    if callable(detector):
        try:
            return bool(detector(filepath, content))
        except Exception:
            return False
    return False


def _no_tests_findings(
    scorable: set[str], graph: dict,
    lang_name: str,
    complexity_map: dict[str, float] | None = None,
) -> list[dict]:
    """Generate findings when there are zero test files."""
    cmap = complexity_map or {}
    # Sort by LOC descending, take top N
    by_loc = sorted(scorable, key=lambda f: -_file_loc(f))
    entries = []
    for f in by_loc[:_MAX_NO_TESTS_ENTRIES]:
        loc = _file_loc(f)
        ic = graph.get(f, {}).get("importer_count", 0)
        is_runtime_entry = _is_runtime_entrypoint(f, lang_name)
        if is_runtime_entry:
            entries.append({
                "file": f,
                "name": "runtime_entrypoint_no_direct_tests",
                "tier": 3,
                "confidence": "medium",
                "summary": (f"Runtime entrypoint ({loc} LOC, {ic} importers) — "
                            f"externally invoked; no direct tests found"),
                "detail": {
                    "kind": "runtime_entrypoint_no_direct_tests",
                    "loc": loc,
                    "importer_count": ic,
                    "loc_weight": 0.0,
                    "entrypoint": True,
                },
            })
            continue
        complexity = cmap.get(f, 0)
        is_complex = complexity >= _COMPLEXITY_TIER_UPGRADE
        is_critical = ic >= 10 or is_complex
        tier = 2 if is_critical else 3
        kind = "untested_critical" if is_critical else "untested_module"
        detail: dict = {"kind": kind, "loc": loc, "importer_count": ic,
                        "loc_weight": _loc_weight(loc)}
        if is_complex:
            detail["complexity_score"] = complexity
        entries.append({
            "file": f,
            "name": "",
            "tier": tier,
            "confidence": "high",
            "summary": f"Untested module ({loc} LOC, {ic} importers) — no test files found",
            "detail": detail,
        })
    return entries


def _import_based_mapping(
    graph: dict,
    test_files: set[str],
    production_files: set[str],
    lang_name: str,
) -> set[str]:
    from .test_coverage_mapping import _import_based_mapping as impl

    return impl(graph, test_files, production_files, lang_name)


def _naming_based_mapping(
    test_files: set[str],
    production_files: set[str],
    lang_name: str,
) -> set[str]:
    from .test_coverage_mapping import _naming_based_mapping as impl

    return impl(test_files, production_files, lang_name)


def _transitive_coverage(
    directly_tested: set[str],
    graph: dict,
    production_files: set[str],
) -> set[str]:
    from .test_coverage_mapping import _transitive_coverage as impl

    return impl(directly_tested, graph, production_files)


def _get_test_files_for_prod(
    prod_file: str,
    test_files: set[str],
    graph: dict,
    lang_name: str,
) -> list[str]:
    from .test_coverage_mapping import _get_test_files_for_prod as impl

    return impl(prod_file, test_files, graph, lang_name)


def _analyze_test_quality_impl(
    test_files: set[str],
    lang_name: str,
) -> dict[str, dict]:
    """Analyze test quality per file."""
    mod = _load_lang_test_coverage_module(lang_name)
    assert_pats = list(getattr(mod, "ASSERT_PATTERNS", []) or [])
    trivial_assert_pats = list(getattr(mod, "TRIVIAL_ASSERT_PATTERNS", []) or [])
    negative_path_pats = list(getattr(mod, "NEGATIVE_PATH_PATTERNS", []) or [])
    import_line_pats = list(getattr(mod, "IMPORT_LINE_PATTERNS", []) or [])
    mock_pats = list(getattr(mod, "MOCK_PATTERNS", []) or [])
    snapshot_pats = list(getattr(mod, "SNAPSHOT_PATTERNS", []) or [])
    test_func_re = getattr(mod, "TEST_FUNCTION_RE", re.compile(r"$^"))
    strip_comments = getattr(mod, "strip_comments", None)

    if not hasattr(test_func_re, "findall"):
        test_func_re = re.compile(r"$^")
    if not callable(strip_comments):
        def _identity_strip(text: str) -> str:
            return text

        strip_comments = _identity_strip

    quality_map: dict[str, dict] = {}

    for test_file in test_files:
        try:
            content = Path(test_file).read_text()
        except (OSError, UnicodeDecodeError) as exc:
            LOGGER.debug(
                "Skipping unreadable test file during quality analysis: %s",
                test_file,
                exc_info=exc,
            )
            continue

        stripped = strip_comments(content)
        lines = stripped.splitlines()
        code_lines = [line for line in lines if line.strip()]

        assertions = sum(1 for line in lines if any(pat.search(line) for pat in assert_pats))
        trivial_assertions = sum(
            1 for line in lines if any(pat.search(line) for pat in trivial_assert_pats)
        )
        trivial_assertions = min(assertions, trivial_assertions)
        behavioral_assertions = max(0, assertions - trivial_assertions)
        negative_path_assertions = sum(
            1 for line in lines if any(pat.search(line) for pat in negative_path_pats)
        )
        mocks = sum(1 for line in lines if any(pat.search(line) for pat in mock_pats))
        snapshots = sum(1 for line in lines if any(pat.search(line) for pat in snapshot_pats))
        import_lines = sum(1 for line in lines if any(pat.search(line) for pat in import_line_pats))
        test_functions = len(test_func_re.findall(stripped))
        assertions_per_test = (assertions / test_functions) if test_functions else 0.0
        trivial_assert_ratio = (trivial_assertions / assertions) if assertions else 0.0
        negative_path_ratio = (
            negative_path_assertions / assertions if assertions else 0.0
        )
        import_density = (
            import_lines / len(code_lines) if code_lines else 0.0
        )
        import_only_likelihood = 0.0
        if assertions > 0 and behavioral_assertions == 0:
            import_only_likelihood += 0.45
        if import_lines > 0:
            import_only_likelihood += min(0.45, import_density)
        if test_functions > 0 and assertions_per_test <= 1.0:
            import_only_likelihood += 0.1
        import_only_likelihood = min(1.0, import_only_likelihood)
        is_import_only = import_only_likelihood >= 0.8

        if test_functions == 0:
            quality = "no_tests"
        elif assertions == 0:
            quality = "assertion_free"
        elif mocks > assertions:
            quality = "over_mocked"
        elif snapshots > 0 and snapshots > assertions * 0.5:
            quality = "snapshot_heavy"
        elif assertions / test_functions < 1:
            quality = "smoke"
        elif assertions / test_functions >= 3:
            quality = "thorough"
        else:
            quality = "adequate"

        base_quality_scores = {
            "no_tests": 0.0,
            "assertion_free": 0.05,
            "smoke": 0.25,
            "over_mocked": 0.35,
            "snapshot_heavy": 0.35,
            "adequate": 0.65,
            "thorough": 0.85,
        }
        quality_score = base_quality_scores.get(quality, 0.5)
        if trivial_assert_ratio >= 0.75:
            quality_score -= 0.30
        elif trivial_assert_ratio >= 0.50:
            quality_score -= 0.20
        if is_import_only:
            quality_score -= 0.25
        if negative_path_assertions > 0:
            quality_score += 0.10
        if assertions_per_test >= 3.0:
            quality_score += 0.05
        quality_score = max(0.0, min(1.0, quality_score))

        quality_map[test_file] = {
            "assertions": assertions,
            "trivial_assertions": trivial_assertions,
            "behavioral_assertions": behavioral_assertions,
            "trivial_assert_ratio": round(trivial_assert_ratio, 3),
            "negative_path_assertions": negative_path_assertions,
            "negative_path_ratio": round(negative_path_ratio, 3),
            "mocks": mocks,
            "test_functions": test_functions,
            "snapshots": snapshots,
            "assertions_per_test": round(assertions_per_test, 3),
            "import_lines": import_lines,
            "import_density": round(import_density, 3),
            "import_only_likelihood": round(import_only_likelihood, 3),
            "import_only": is_import_only,
            "quality_score": round(quality_score, 3),
            "quality": quality,
        }

    return quality_map


def _analyze_test_quality(
    test_files: set[str],
    lang_name: str,
) -> dict[str, dict]:
    return _analyze_test_quality_impl(test_files, lang_name)


# Complexity score threshold for upgrading test coverage tier.
# Files above this are risky enough without tests to warrant tier 2.
_COMPLEXITY_TIER_UPGRADE = 20


def _quality_risk_level(loc: int, importer_count: int, complexity: float) -> str:
    """Classify module test-risk level for quality confidence gating."""
    if importer_count >= 10 or complexity >= _COMPLEXITY_TIER_UPGRADE or loc >= 400:
        return "high"
    if importer_count >= 4 or complexity >= 12 or loc >= 200:
        return "medium"
    return "low"


def _quality_threshold(risk: str) -> float:
    """Minimum acceptable test quality score by risk level."""
    return {"high": 0.60, "medium": 0.50}.get(risk, 0.35)


def _generate_findings(
    scorable: set[str],
    directly_tested: set[str],
    transitively_tested: set[str],
    test_quality: dict[str, dict],
    graph: dict,
    lang_name: str,
    complexity_map: dict[str, float] | None = None,
) -> list[dict]:
    """Generate test coverage findings from the analysis results."""
    entries: list[dict] = []
    cmap = complexity_map or {}

    # Collect all test files for mapping
    test_files = set(test_quality.keys())

    for f in scorable:
        loc = _file_loc(f)
        ic = graph.get(f, {}).get("importer_count", 0)
        lw = _loc_weight(loc)

        if f in directly_tested:
            # Check quality of the test(s) for this file
            related_tests = _get_test_files_for_prod(f, test_files, graph, lang_name)
            quality_scores: list[float] = []
            total_negative_path = 0
            total_behavioral = 0
            total_assertions = 0
            for tf in related_tests:
                tq = test_quality.get(tf)
                if tq is None:
                    continue
                quality_scores.append(float(tq.get("quality_score", 0.0) or 0.0))
                total_negative_path += int(tq.get("negative_path_assertions", 0) or 0)
                total_behavioral += int(tq.get("behavioral_assertions", 0) or 0)
                total_assertions += int(tq.get("assertions", 0) or 0)

                if tq["quality"] == "assertion_free":
                    entries.append({
                        "file": f,
                        "name": f"assertion_free::{os.path.basename(tf)}",
                        "tier": 3,
                        "confidence": "medium",
                        "summary": (f"Assertion-free test: {os.path.basename(tf)} "
                                    f"has {tq['test_functions']} test functions but 0 assertions"),
                        "detail": {"kind": "assertion_free_test", "test_file": tf,
                                   "test_functions": tq["test_functions"],
                                   "loc_weight": lw},
                    })
                elif tq["quality"] == "smoke":
                    entries.append({
                        "file": f,
                        "name": f"shallow::{os.path.basename(tf)}",
                        "tier": 3,
                        "confidence": "medium",
                        "summary": (f"Shallow tests: {os.path.basename(tf)} has "
                                    f"{tq['assertions']} assertions across "
                                    f"{tq['test_functions']} test functions"),
                        "detail": {"kind": "shallow_tests", "test_file": tf,
                                   "assertions": tq["assertions"],
                                   "test_functions": tq["test_functions"],
                                   "loc_weight": lw},
                    })
                elif tq["quality"] == "over_mocked":
                    entries.append({
                        "file": f,
                        "name": f"over_mocked::{os.path.basename(tf)}",
                        "tier": 3,
                        "confidence": "low",
                        "summary": (f"Over-mocked tests: {os.path.basename(tf)} has "
                                    f"{tq['mocks']} mocks vs {tq['assertions']} assertions"),
                        "detail": {"kind": "over_mocked", "test_file": tf,
                                   "mocks": tq["mocks"], "assertions": tq["assertions"],
                                   "loc_weight": lw},
                    })
                elif tq["quality"] == "snapshot_heavy":
                    entries.append({
                        "file": f,
                        "name": f"snapshot_heavy::{os.path.basename(tf)}",
                        "tier": 3,
                        "confidence": "low",
                        "summary": (f"Snapshot-heavy tests: {os.path.basename(tf)} has "
                                    f"{tq['snapshots']} snapshots vs {tq['assertions']} assertions"),
                        "detail": {"kind": "snapshot_heavy", "test_file": tf,
                                   "snapshots": tq["snapshots"],
                                   "assertions": tq["assertions"],
                                   "loc_weight": lw},
                    })
                if tq.get("import_only", False):
                    entries.append({
                        "file": f,
                        "name": f"import_only::{os.path.basename(tf)}",
                        "tier": 3,
                        "confidence": "medium",
                        "summary": (
                            f"Import-dominant tests: {os.path.basename(tf)} appears import-only "
                            f"(score {tq.get('import_only_likelihood', 0):.2f})"
                        ),
                        "detail": {
                            "kind": "import_only_tests",
                            "test_file": tf,
                            "import_only_likelihood": tq.get("import_only_likelihood", 0.0),
                            "import_lines": tq.get("import_lines", 0),
                            "assertions": tq.get("assertions", 0),
                            "trivial_assertions": tq.get("trivial_assertions", 0),
                            "loc_weight": lw,
                        },
                    })
                if (tq.get("assertions", 0) > 0
                        and float(tq.get("trivial_assert_ratio", 0.0) or 0.0) >= 0.60):
                    entries.append({
                        "file": f,
                        "name": f"trivial_asserts::{os.path.basename(tf)}",
                        "tier": 3,
                        "confidence": "medium",
                        "summary": (
                            f"Trivial assertion-heavy tests: {os.path.basename(tf)} has "
                            f"{tq.get('trivial_assertions', 0)}/{tq.get('assertions', 0)} "
                            "trivial assertions"
                        ),
                        "detail": {
                            "kind": "trivial_assert_tests",
                            "test_file": tf,
                            "trivial_assertions": tq.get("trivial_assertions", 0),
                            "assertions": tq.get("assertions", 0),
                            "trivial_assert_ratio": tq.get("trivial_assert_ratio", 0.0),
                            "loc_weight": lw,
                        },
                    })

            if quality_scores:
                best_score = max(quality_scores)
                avg_score = sum(quality_scores) / len(quality_scores)
                complexity = cmap.get(f, 0)
                risk = _quality_risk_level(loc, ic, complexity)
                threshold = _quality_threshold(risk)
                low_confidence = best_score < threshold
                if low_confidence:
                    tier = 2 if risk == "high" else 3
                    confidence = "high" if risk == "high" else "medium"
                    reason = f"best quality score {best_score:.2f} below threshold {threshold:.2f}"
                    detail: dict = {
                        "kind": "test_quality_low_confidence",
                        "risk": risk,
                        "reason": reason,
                        "best_quality_score": round(best_score, 3),
                        "avg_quality_score": round(avg_score, 3),
                        "quality_threshold": threshold,
                        "test_files": len(quality_scores),
                        "assertions": total_assertions,
                        "behavioral_assertions": total_behavioral,
                        "negative_path_assertions": total_negative_path,
                        "importer_count": ic,
                        "loc": loc,
                        "loc_weight": lw,
                    }
                    if complexity >= _COMPLEXITY_TIER_UPGRADE:
                        detail["complexity_score"] = complexity
                    entries.append({
                        "file": f,
                        "name": "low_confidence",
                        "tier": tier,
                        "confidence": confidence,
                        "summary": (
                            f"Low-confidence tests for module ({loc} LOC, {ic} importers): {reason}"
                        ),
                        "detail": detail,
                    })

        elif f in transitively_tested:
            complexity = cmap.get(f, 0)
            is_complex = complexity >= _COMPLEXITY_TIER_UPGRADE
            tier = 2 if (ic >= 10 or is_complex) else 3
            detail: dict = {"kind": "transitive_only", "loc": loc, "importer_count": ic,
                            "loc_weight": lw}
            if is_complex:
                detail["complexity_score"] = complexity
            entries.append({
                "file": f,
                "name": "transitive_only",
                "tier": tier,
                "confidence": "medium",
                "summary": (f"No direct tests ({loc} LOC, {ic} importers) "
                            f"— covered only via imports from tested modules"),
                "detail": detail,
            })

        else:
            # Untested
            complexity = cmap.get(f, 0)
            is_runtime_entry = _is_runtime_entrypoint(f, lang_name)
            if is_runtime_entry:
                entries.append({
                    "file": f,
                    "name": "runtime_entrypoint_no_direct_tests",
                    "tier": 3,
                    "confidence": "medium",
                    "summary": (f"Runtime entrypoint ({loc} LOC, {ic} importers) "
                                f"— externally invoked; no direct tests found"),
                    "detail": {"kind": "runtime_entrypoint_no_direct_tests", "loc": loc,
                               "importer_count": ic, "loc_weight": 0.0, "entrypoint": True},
                })
                continue
            is_complex = complexity >= _COMPLEXITY_TIER_UPGRADE
            if ic >= 10 or is_complex:
                detail = {"kind": "untested_critical", "loc": loc, "importer_count": ic,
                          "loc_weight": lw}
                if is_complex:
                    detail["complexity_score"] = complexity
                entries.append({
                    "file": f,
                    "name": "untested_critical",
                    "tier": 2,
                    "confidence": "high",
                    "summary": (f"Untested critical module ({loc} LOC, {ic} importers) "
                                f"— high blast radius"),
                    "detail": detail,
                })
            else:
                entries.append({
                    "file": f,
                    "name": "untested_module",
                    "tier": 3,
                    "confidence": "high",
                    "summary": f"Untested module ({loc} LOC, {ic} importers)",
                    "detail": {"kind": "untested_module", "loc": loc, "importer_count": ic,
                               "loc_weight": lw},
                })

    return entries
