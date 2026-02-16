"""Base abstractions for multi-language support."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..state import Finding, make_finding
from ..utils import PROJECT_ROOT, log, resolve_path


@dataclass
class DetectorPhase:
    """A single phase in the scan pipeline.

    Each phase runs one or more detectors and returns normalized findings.
    The `run` function handles both detection AND normalization (converting
    raw detector output to findings with tiers/confidence).
    """
    label: str
    run: Callable[[Path, LangConfig], tuple[list[Finding], dict[str, int]]]
    slow: bool = False


@dataclass
class FixResult:
    """Return type for fixer wrappers that need to carry metadata."""
    entries: list[dict]
    skip_reasons: dict[str, int] = field(default_factory=dict)


@dataclass
class FixerConfig:
    """Configuration for an auto-fixer."""
    label: str
    detect: Callable
    fix: Callable
    detector: str           # finding detector name (for state resolution)
    verb: str = "Fixed"
    dry_verb: str = "Would fix"
    post_fix: Callable | None = None


@dataclass
class BoundaryRule:
    """A coupling boundary: `protected` dir should not be imported from `forbidden_from`."""
    protected: str          # e.g. "shared/"
    forbidden_from: str     # e.g. "tools/"
    label: str              # e.g. "shared→tools"


@dataclass(frozen=True)
class LangValueSpec:
    """Typed language option/setting schema entry."""

    type: type
    default: object
    description: str = ""


@dataclass
class LangConfig:
    """Language configuration — everything the pipeline needs to scan a codebase."""

    name: str
    extensions: list[str]
    exclusions: list[str]
    default_src: str                                    # relative to PROJECT_ROOT

    # Dep graph builder (language-specific import parsing)
    build_dep_graph: Callable[[Path], dict]

    # Entry points (not orphaned even with 0 importers)
    entry_patterns: list[str]
    barrel_names: set[str]

    # Detector phases (ordered)
    phases: list[DetectorPhase] = field(default_factory=list)

    # Fixer registry
    fixers: dict[str, FixerConfig] = field(default_factory=dict)

    # Area classification (project-specific grouping)
    get_area: Callable[[str], str] | None = None

    # Commands for `detect` subcommand (language-specific overrides)
    # Keys serve as the valid detector name list.
    detect_commands: dict[str, Callable] = field(default_factory=dict)

    # Function extractor (for duplicate detection). Returns list[FunctionInfo].
    extract_functions: Callable[[Path], list] | None = None

    # Coupling boundaries (optional, project-specific)
    boundaries: list[BoundaryRule] = field(default_factory=list)

    # Unused detection tool command (for post-fix checklist)
    typecheck_cmd: str = ""

    # File finder: (path) -> list[str]
    file_finder: Callable | None = None

    # Structural analysis thresholds
    large_threshold: int = 500
    complexity_threshold: int = 15
    default_scan_profile: str = "full"

    # Language-specific persisted settings and per-run runtime options.
    setting_specs: dict[str, LangValueSpec] = field(default_factory=dict)
    # Deprecated top-level config keys -> namespaced setting key.
    legacy_setting_keys: dict[str, str] = field(default_factory=dict)
    runtime_option_specs: dict[str, LangValueSpec] = field(default_factory=dict)
    # argparse attribute -> runtime option key (for optional compatibility aliases).
    runtime_option_aliases: dict[str, str] = field(default_factory=dict)

    # Project-level files that indicate this language is present
    detect_markers: list[str] = field(default_factory=list)

    # External test discovery (outside scanned path)
    external_test_dirs: list[str] = field(default_factory=lambda: ["tests", "test"])
    test_file_extensions: list[str] = field(default_factory=list)

    # Review-context language hooks
    review_module_patterns_fn: Callable[[str], list[str]] | None = None
    review_api_surface_fn: Callable[[dict[str, str]], dict] | None = None
    review_guidance: dict = field(default_factory=dict)
    review_low_value_pattern: object | None = None
    holistic_review_dimensions: list[str] = field(default_factory=list)
    migration_pattern_pairs: list[tuple[str, object, object]] = field(default_factory=list)
    migration_mixed_extensions: set[str] = field(default_factory=set)

    # Zone classification
    zone_rules: list = field(default_factory=list)
    _zone_map: object = field(default=None, repr=False)  # FileZoneMap, set at scan time
    _dep_graph: object = field(default=None, repr=False)  # dep graph, set at scan time
    _review_cache: dict = field(default_factory=dict, repr=False)  # review cache, set before scan
    _review_max_age_days: int = field(default=30, repr=False)  # from config, set before scan
    _props_threshold: int = field(default=0, repr=False)  # from config, 0 = use default (14)
    _complexity_map: dict = field(default_factory=dict, repr=False)  # file→score, set at scan time
    _runtime_settings: dict = field(default_factory=dict, repr=False)
    _runtime_options: dict = field(default_factory=dict, repr=False)

    @staticmethod
    def _clone_default(default: object) -> object:
        return copy.deepcopy(default)

    @classmethod
    def _coerce_value(cls, raw: object, expected: type, default: object) -> object:
        """Best-effort coercion for config/CLI values."""
        fallback = cls._clone_default(default)
        if raw is None:
            return fallback

        if expected is bool:
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str):
                lowered = raw.strip().lower()
                if lowered in {"1", "true", "yes", "on"}:
                    return True
                if lowered in {"0", "false", "no", "off"}:
                    return False
                return fallback
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                return bool(raw)
            return fallback

        if expected is int:
            if isinstance(raw, bool):
                return fallback
            try:
                return int(raw)
            except (TypeError, ValueError):
                return fallback

        if expected is float:
            if isinstance(raw, bool):
                return fallback
            try:
                return float(raw)
            except (TypeError, ValueError):
                return fallback

        if expected is str:
            return raw if isinstance(raw, str) else str(raw)

        if expected is list:
            return raw if isinstance(raw, list) else fallback

        if expected is dict:
            return raw if isinstance(raw, dict) else fallback

        return raw if isinstance(raw, expected) else fallback

    def normalize_settings(self, values: dict[str, object] | None) -> dict[str, object]:
        values = values if isinstance(values, dict) else {}
        normalized: dict[str, object] = {}
        for key, spec in self.setting_specs.items():
            raw = values.get(key, spec.default)
            normalized[key] = self._coerce_value(raw, spec.type, spec.default)
        return normalized

    def normalize_runtime_options(
        self,
        values: dict[str, object] | None,
        *,
        strict: bool = False,
    ) -> dict[str, object]:
        values = values if isinstance(values, dict) else {}
        specs = self.runtime_option_specs
        if strict:
            unknown = sorted(set(values) - set(specs))
            if unknown:
                raise KeyError(
                    f"Unknown runtime option(s) for {self.name}: {', '.join(unknown)}"
                )
        normalized: dict[str, object] = {}
        for key, spec in specs.items():
            raw = values.get(key, spec.default)
            normalized[key] = self._coerce_value(raw, spec.type, spec.default)
        return normalized

    def set_runtime_context(
        self,
        *,
        settings: dict[str, object] | None = None,
        options: dict[str, object] | None = None,
    ) -> None:
        """Apply per-language config settings and per-command runtime options."""
        self._runtime_settings = self.normalize_settings(settings)
        self._runtime_options = self.normalize_runtime_options(options)

    def clear_runtime_context(self) -> None:
        """Clear per-command runtime values so LangConfig instances stay isolated."""
        self._runtime_settings = {}
        self._runtime_options = {}

    def runtime_setting(self, key: str, default: object | None = None) -> object:
        if key in self._runtime_settings:
            return self._runtime_settings[key]
        spec = self.setting_specs.get(key)
        if spec:
            return self._clone_default(spec.default)
        return default

    def runtime_option(self, key: str, default: object | None = None) -> object:
        if key in self._runtime_options:
            return self._runtime_options[key]
        spec = self.runtime_option_specs.get(key)
        if spec:
            return self._clone_default(spec.default)
        return default


from .finding_factories import (  # noqa: F401
    make_unused_findings, make_dupe_findings, make_single_use_findings,
    make_cycle_findings, make_orphaned_findings, SMELL_TIER_MAP,
    make_smell_findings, make_passthrough_findings, make_facade_findings,
)


def add_structural_signal(structural: dict, file: str, signal: str, detail: dict):
    """Add a complexity signal to the per-file structural dict.

    Accumulates signals per file so they can be merged into tiered findings.
    """
    f = resolve_path(file)
    structural.setdefault(f, {"signals": [], "detail": {}})
    structural[f]["signals"].append(signal)
    structural[f]["detail"].update(detail)


def merge_structural_signals(structural: dict, stderr_fn,
                              *, complexity_only_min: int = 35) -> list[Finding]:
    """Convert per-file structural signals into tiered findings.

    3+ signals -> T4/high (needs decomposition).
    1-2 signals -> T3/medium.
    Complexity-only files (no large/god signals) need score >= complexity_only_min
    to be flagged — lower complexity in small files is normal, not decomposition-worthy.
    """
    results = []
    suppressed = 0
    for filepath, data in structural.items():
        if "loc" not in data["detail"]:
            try:
                p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
                data["detail"]["loc"] = len(p.read_text().splitlines())
            except (OSError, UnicodeDecodeError):
                data["detail"]["loc"] = 0

        # Suppress complexity-only findings below the elevated threshold
        signals = data["signals"]
        is_complexity_only = all(s.startswith("complexity") for s in signals)
        if is_complexity_only:
            score = data["detail"].get("complexity_score", 0)
            if score < complexity_only_min:
                suppressed += 1
                continue

        signal_count = len(signals)
        tier = 4 if signal_count >= 3 else 3
        confidence = "high" if signal_count >= 3 else "medium"
        summary = "Needs decomposition: " + " / ".join(signals)
        results.append(make_finding(
            "structural", filepath, "",
            tier=tier, confidence=confidence,
            summary=summary,
            detail=data["detail"],
        ))
    if suppressed:
        stderr_fn(f"         {suppressed} complexity-only files below threshold (< {complexity_only_min})")
    stderr_fn(f"         -> {len(results)} structural findings")
    return results


def phase_dupes(path: Path, lang: LangConfig) -> tuple[list[Finding], dict[str, int]]:
    """Shared phase runner: detect duplicate functions via lang.extract_functions.

    When a zone map is available, filters out functions from zone-excluded files
    before the O(n^2) comparison to avoid test/config/generated false positives.
    """
    from ..detectors.dupes import detect_duplicates
    from ..utils import log
    functions = lang.extract_functions(path)

    # Filter out functions from zone-excluded files
    if lang._zone_map is not None:
        from ..zones import EXCLUDED_ZONES
        before = len(functions)
        functions = [f for f in functions
                     if lang._zone_map.get(getattr(f, "file", "")) not in EXCLUDED_ZONES]
        excluded = before - len(functions)
        if excluded:
            log(f"         zones: {excluded} functions excluded (non-production)")

    entries, total_functions = detect_duplicates(functions)
    findings = make_dupe_findings(entries, log)
    return findings, {"dupes": total_functions}


# ── Shared phase runners ──────────────────────────────────────


def find_external_test_files(path: Path, lang: LangConfig) -> set[str]:
    """Find test files in standard locations outside the scanned path."""
    import os
    extra = set()
    test_dirs = lang.external_test_dirs or ["tests", "test"]
    exts = tuple(lang.test_file_extensions or lang.extensions)
    for test_dir in test_dirs:
        d = PROJECT_ROOT / test_dir
        if not d.is_dir():
            continue
        try:
            d.resolve().relative_to(path.resolve())
            continue  # test_dir is inside scanned path, zone_map already has it
        except ValueError:
            pass
        for root, _, files in os.walk(d):
            for f in files:
                if any(f.endswith(e) for e in exts):
                    extra.add(os.path.join(root, f))
    return extra


def phase_security(path: Path, lang: LangConfig) -> tuple[list[Finding], dict[str, int]]:
    """Shared phase: detect security issues (cross-language + lang-specific)."""
    from ..detectors.security import detect_security_issues
    from ..zones import filter_entries

    zm = lang._zone_map
    files = lang.file_finder(path) if lang.file_finder else []
    entries, potential = detect_security_issues(files, zm, lang.name)

    # Also call lang-specific security detectors if available
    if hasattr(lang, 'detect_lang_security'):
        lang_entries, _ = lang.detect_lang_security(files, zm)
        entries.extend(lang_entries)

    entries = filter_entries(zm, entries, "security")

    results = []
    for e in entries:
        finding = make_finding(
            "security", e["file"], e["name"],
            tier=e["tier"], confidence=e["confidence"],
            summary=e["summary"], detail=e["detail"],
        )
        # Stamp zone so scoring zone override works
        if zm is not None:
            finding["zone"] = zm.get(e["file"]).value
        results.append(finding)

    if results:
        log(f"         security: {len(results)} findings ({potential} files scanned)")
    else:
        log(f"         security: clean ({potential} files scanned)")

    return results, {"security": potential}


def phase_test_coverage(path: Path, lang: LangConfig) -> tuple[list[Finding], dict[str, int]]:
    """Shared phase: detect test coverage gaps."""
    from ..detectors.test_coverage import detect_test_coverage
    from ..zones import filter_entries

    zm = lang._zone_map
    if zm is None:
        return [], {}

    graph = lang._dep_graph or lang.build_dep_graph(path)
    extra = find_external_test_files(path, lang)
    entries, potential = detect_test_coverage(graph, zm, lang.name,
                                              extra_test_files=extra or None,
                                              complexity_map=lang._complexity_map or None)
    entries = filter_entries(zm, entries, "test_coverage")

    results = []
    for e in entries:
        results.append(make_finding(
            "test_coverage", e["file"], e.get("name", ""),
            tier=e["tier"], confidence=e["confidence"],
            summary=e["summary"], detail=e.get("detail", {}),
        ))

    if results:
        log(f"         test coverage: {len(results)} findings ({potential} production files)")
    else:
        log(f"         test coverage: clean ({potential} production files)")

    return results, {"test_coverage": potential}


def phase_private_imports(path: Path, lang: LangConfig) -> tuple[list[Finding], dict[str, int]]:
    """Shared phase: detect cross-module private imports."""
    from ..zones import filter_entries

    if not hasattr(lang, "detect_private_imports"):
        return [], {}

    zm = lang._zone_map
    graph = lang._dep_graph or lang.build_dep_graph(path)

    entries, potential = lang.detect_private_imports(graph, zm)
    entries = filter_entries(zm, entries, "private_imports")

    results = []
    for e in entries:
        results.append(make_finding(
            "private_imports", e["file"], e["name"],
            tier=e["tier"], confidence=e["confidence"],
            summary=e["summary"], detail=e.get("detail", {}),
        ))

    if results:
        log(f"         private imports: {len(results)} findings ({potential} files scanned)")
    else:
        log(f"         private imports: clean ({potential} files scanned)")

    return results, {"private_imports": potential}


def phase_subjective_review(path: Path, lang: LangConfig) -> tuple[list[Finding], dict[str, int]]:
    """Shared phase: detect files missing subjective design review."""
    from ..detectors.review_coverage import detect_review_coverage, detect_holistic_review_staleness

    zm = lang._zone_map
    max_age = lang._review_max_age_days
    files = lang.file_finder(path) if lang.file_finder else []
    entries, potential = detect_review_coverage(files, zm, lang._review_cache, lang.name,
                                                max_age_days=max_age)

    # Also check holistic review staleness
    holistic_entries = detect_holistic_review_staleness(
        lang._review_cache, total_files=len(files), max_age_days=max_age)
    entries.extend(holistic_entries)

    results = []
    for e in entries:
        finding = make_finding(
            "subjective_review", e["file"], e["name"],
            tier=e["tier"], confidence=e["confidence"],
            summary=e["summary"], detail=e["detail"],
        )
        results.append(finding)

    if results:
        log(f"         subjective review: {len(results)} findings ({potential} reviewable files)")
    else:
        log(f"         subjective review: clean ({potential} reviewable files)")

    return results, {"subjective_review": potential}


def detector_phase_test_coverage() -> DetectorPhase:
    """Canonical shared detector phase entry for test coverage."""
    return DetectorPhase("Test coverage", phase_test_coverage)


def detector_phase_security() -> DetectorPhase:
    """Canonical shared detector phase entry for security."""
    return DetectorPhase("Security", phase_security)


def detector_phase_subjective_review() -> DetectorPhase:
    """Canonical shared detector phase entry for subjective review coverage."""
    return DetectorPhase("Subjective review", phase_subjective_review)


def detector_phase_duplicates() -> DetectorPhase:
    """Canonical shared detector phase entry for duplicate detection."""
    return DetectorPhase("Duplicates", phase_dupes, slow=True)


def shared_subjective_duplicates_tail(
    *,
    pre_duplicates: list[DetectorPhase] | None = None,
) -> list[DetectorPhase]:
    """Shared review tail: subjective review, optional custom phases, then duplicates."""
    phases = [detector_phase_subjective_review()]
    if pre_duplicates:
        phases.extend(pre_duplicates)
    phases.append(detector_phase_duplicates())
    return phases
