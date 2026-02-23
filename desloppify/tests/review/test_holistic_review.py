"""Tests for holistic codebase-wide review support."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import desloppify.core._internal.text_utils as _utils_text_mod
import desloppify.file_discovery as _file_discovery_mod
from desloppify import utils as _u
from desloppify.engine.detectors.review_coverage import detect_holistic_review_staleness
from desloppify.state import path_scoped_findings
from desloppify.state import empty_state
from desloppify.intelligence.narrative.core import _count_open_by_detector
from desloppify.intelligence.review import (
    DIMENSIONS,
    DIMENSION_PROMPTS,
    HOLISTIC_DIMENSIONS_BY_LANG,
    REVIEW_SYSTEM_PROMPT,
    build_holistic_context,
    generate_remediation_plan,
)
from desloppify.intelligence.review import (
    import_holistic_findings as _import_holistic_findings_impl,
)
from desloppify.intelligence.review import (
    prepare_holistic_review as _prepare_holistic_review_impl,
)
from desloppify.intelligence.review.context import file_excerpt
from desloppify.intelligence.review._context.patterns import (
    extract_imported_names,
)
from desloppify.intelligence.review.prepare import HolisticReviewPrepareOptions
from desloppify.intelligence.review.prepare_batches import (
    build_investigation_batches as _build_investigation_batches,
)
from desloppify.intelligence.review.prepare_batches import filter_batches_to_dimensions
from desloppify.intelligence.review._prepare.helpers import (
    HOLISTIC_WORKFLOW as _HOLISTIC_WORKFLOW,
)
from desloppify.scoring import (
    HOLISTIC_POTENTIAL,
    detector_pass_rate,
)


@pytest.fixture
def patch_project_root(monkeypatch):
    """Patch PROJECT_ROOT via RuntimeContext so all consumers see the override."""
    from desloppify.core.runtime_state import current_runtime_context
    ctx = current_runtime_context()
    def _patch(tmp_path):
        monkeypatch.setattr(ctx, "project_root", tmp_path)
        monkeypatch.setattr(_u, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(_utils_text_mod, "PROJECT_ROOT", tmp_path)
        _file_discovery_mod._clear_source_file_cache()
    return _patch


# ── Helpers ──────────────────────────────────────────────────────


def _make_file(tmpdir, name, lines=30, content=None):
    """Create a file with content."""
    p = os.path.join(tmpdir, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        if content is not None:
            f.write(content)
        else:
            for i in range(lines):
                f.write(f"def func_{i}(): pass\n")
    return p


def _mock_lang(files=None):
    lang = MagicMock()
    lang.name = "python"
    lang.file_finder = MagicMock(return_value=files or [])
    lang.zone_map = None
    lang.dep_graph = None
    lang.zone_rules = []
    lang.build_dep_graph = None
    return lang


def prepare_holistic_review(
    path,
    lang,
    state,
    *,
    dimensions=None,
    files=None,
    include_full_sweep=True,
):
    return _prepare_holistic_review_impl(
        path,
        lang,
        state,
        options=HolisticReviewPrepareOptions(
            dimensions=dimensions,
            files=files,
            include_full_sweep=include_full_sweep,
        ),
    )


def import_holistic_findings(findings_data, state, lang_name):
    payload = findings_data if isinstance(findings_data, dict) else {"findings": findings_data}
    return _import_holistic_findings_impl(payload, state, lang_name)


# ===================================================================
# DIMENSIONS and prompts
# ===================================================================


class TestHolisticConstants:
    def test_fifteen_dimensions(self):
        assert len(DIMENSIONS) == 20

    def test_all_dimensions_have_prompts(self):
        for dim in DIMENSIONS:
            assert dim in DIMENSION_PROMPTS, f"Missing prompt for {dim}"

    def test_prompts_have_required_fields(self):
        for dim, prompt in DIMENSION_PROMPTS.items():
            assert "description" in prompt, f"{dim} missing description"
            assert "look_for" in prompt, f"{dim} missing look_for"
            assert "skip" in prompt, f"{dim} missing skip"
            assert len(prompt["look_for"]) >= 2, f"{dim} has too few look_for items"

    def test_system_prompt_exists(self):
        assert "IMPORT GUARD" in REVIEW_SYSTEM_PROMPT
        assert "related_files" in REVIEW_SYSTEM_PROMPT


# ===================================================================
# HOLISTIC_DIMENSIONS_BY_LANG
# ===================================================================


class TestHolisticDimensionsByLang:
    def test_curated_dims_are_subset_of_superset(self):
        for lang_name, dims in HOLISTIC_DIMENSIONS_BY_LANG.items():
            for dim in dims:
                assert dim in DIMENSIONS, (
                    f"{lang_name} dim {dim!r} not in DIMENSIONS"
                )

    def test_all_curated_dims_have_prompts(self):
        for lang_name, dims in HOLISTIC_DIMENSIONS_BY_LANG.items():
            for dim in dims:
                assert dim in DIMENSION_PROMPTS, (
                    f"{lang_name} dim {dim!r} missing prompt"
                )

    def test_unknown_lang_falls_back_to_full(self, tmp_path):
        f1 = _make_file(str(tmp_path), "module.xx", lines=50)
        lang = _mock_lang([f1])
        lang.name = "unknownlang"  # not in HOLISTIC_DIMENSIONS_BY_LANG
        state = empty_state()

        data = prepare_holistic_review(tmp_path, lang, state, files=[f1])

        assert len(data["dimensions"]) == len(DIMENSIONS)

    def test_python_gets_eleven_dims(self, tmp_path):
        f1 = _make_file(str(tmp_path), "module.py", lines=50)
        lang = _mock_lang([f1])
        state = empty_state()

        data = prepare_holistic_review(tmp_path, lang, state, files=[f1])

        assert len(data["dimensions"]) == 12
        assert "package_organization" in data["dimensions"]
        assert "api_surface_coherence" not in data["dimensions"]
        assert "high_level_elegance" in data["dimensions"]
        assert "mid_level_elegance" in data["dimensions"]
        assert "low_level_elegance" in data["dimensions"]
        assert "design_coherence" in data["dimensions"]

    def test_typescript_gets_twelve_dims(self, tmp_path):
        f1 = _make_file(str(tmp_path), "module.ts", lines=50)
        lang = _mock_lang([f1])
        lang.name = "typescript"
        state = empty_state()

        data = prepare_holistic_review(tmp_path, lang, state, files=[f1])

        assert len(data["dimensions"]) == 13
        assert "api_surface_coherence" in data["dimensions"]
        assert "package_organization" in data["dimensions"]
        assert "high_level_elegance" in data["dimensions"]
        assert "mid_level_elegance" in data["dimensions"]
        assert "low_level_elegance" in data["dimensions"]


# ===================================================================
# build_holistic_context
# ===================================================================


class TestBuildHolisticContext:
    def test_returns_all_sections(self, tmp_path):
        f1 = _make_file(str(tmp_path), "src/module_a.py", lines=50)
        f2 = _make_file(str(tmp_path), "src/module_b.py", lines=50)
        lang = _mock_lang([f1, f2])
        state = empty_state()

        ctx = build_holistic_context(tmp_path, lang, state, files=[f1, f2])

        assert "architecture" in ctx
        assert "coupling" in ctx
        assert "conventions" in ctx
        assert "errors" in ctx
        assert "abstractions" in ctx
        assert "dependencies" in ctx
        assert "testing" in ctx
        assert "api_surface" in ctx
        assert "structure" in ctx
        assert "codebase_stats" in ctx

    def test_codebase_stats(self, tmp_path):
        f1 = _make_file(str(tmp_path), "module.py", lines=100)
        lang = _mock_lang([f1])
        state = empty_state()

        ctx = build_holistic_context(tmp_path, lang, state, files=[f1])

        assert ctx["codebase_stats"]["total_files"] == 1
        assert ctx["codebase_stats"]["total_loc"] == 100

    def test_util_files_detected(self, tmp_path):
        util_file = _make_file(str(tmp_path), "utils.py", lines=200)
        other_file = _make_file(str(tmp_path), "main.py", lines=50)
        lang = _mock_lang([util_file, other_file])
        state = empty_state()

        ctx = build_holistic_context(
            tmp_path, lang, state, files=[util_file, other_file]
        )

        util_names = [u["file"] for u in ctx["abstractions"]["util_files"]]
        # Should find the utils file
        assert any("utils" in n for n in util_names)

    def test_abstraction_hotspots_detected(self, tmp_path):
        wrapper_file = _make_file(
            str(tmp_path),
            "wrappers.py",
            content=(
                "def outer(*args, **kwargs):\n"
                "    return inner(*args, **kwargs)\n\n"
                "def inner(*args, **kwargs):\n"
                "    return args\n\n"
                "def wide(a, b, c, d, e, f, g, h):\n"
                "    return a\n"
            ),
        )
        iface_file = _make_file(
            str(tmp_path),
            "iface.py",
            content=(
                "class PaymentProtocol:\n"
                "    pass\n\n"
                "class StripeGateway(PaymentProtocol):\n"
                "    pass\n"
            ),
        )
        chain_file = _make_file(
            str(tmp_path),
            "chain.py",
            content=(
                "def run():\n"
                "    return services.billing.client.gateway.adapter.fetch.value\n"
            ),
        )
        lang = _mock_lang([wrapper_file, iface_file, chain_file])
        state = empty_state()

        ctx = build_holistic_context(
            tmp_path,
            lang,
            state,
            files=[wrapper_file, iface_file, chain_file],
        )
        abstractions = ctx["abstractions"]

        assert abstractions["summary"]["total_wrappers"] >= 1
        assert "pass_through_wrappers" in abstractions
        assert "one_impl_interfaces" in abstractions
        assert "indirection_hotspots" in abstractions
        assert "wide_param_bags" in abstractions
        assert "sub_axes" in abstractions
        assert "abstraction_leverage" in abstractions["sub_axes"]
        assert "indirection_cost" in abstractions["sub_axes"]
        assert "interface_honesty" in abstractions["sub_axes"]

    def test_empty_files_list(self, tmp_path):
        lang = _mock_lang([])
        state = empty_state()

        ctx = build_holistic_context(tmp_path, lang, state, files=[])

        assert ctx["codebase_stats"]["total_files"] == 0


# ===================================================================
# prepare_holistic_review
# ===================================================================


class TestPrepareHolisticReview:
    def test_returns_holistic_mode(self, tmp_path):
        f1 = _make_file(str(tmp_path), "module.py", lines=50)
        lang = _mock_lang([f1])
        state = empty_state()

        data = prepare_holistic_review(tmp_path, lang, state, files=[f1])

        assert data["mode"] == "holistic"
        assert data["command"] == "review"
        # Python lang gets curated 12-dim subset
        assert len(data["dimensions"]) == 12
        assert "holistic_context" in data
        assert "system_prompt" in data

    def test_custom_dimensions(self, tmp_path):
        f1 = _make_file(str(tmp_path), "module.py", lines=50)
        lang = _mock_lang([f1])
        state = empty_state()

        data = prepare_holistic_review(
            tmp_path,
            lang,
            state,
            dimensions=["cross_module_architecture", "dependency_health"],
            files=[f1],
        )

        assert data["dimensions"] == ["cross_module_architecture", "dependency_health"]


# ===================================================================
# import_holistic_findings
# ===================================================================


class TestImportHolisticFindings:
    def test_basic_import(self):
        state = empty_state()
        findings_data = [
            {
                "dimension": "cross_module_architecture",
                "identifier": "god_module",
                "summary": "utils.py is imported by 90% of modules",
                "confidence": "high",
                "related_files": ["src/utils.py", "src/a.py", "src/b.py"],
                "evidence": ["90% of modules import utils.py"],
                "suggestion": "Split utils.py into domain-specific modules",
            }
        ]

        diff = import_holistic_findings(findings_data, state, "python")

        assert diff["new"] == 1
        findings = list(state["findings"].values())
        assert len(findings) == 1
        f = findings[0]
        assert f["file"] == "."
        assert f["detector"] == "review"
        assert f["detail"]["holistic"] is True
        assert "related_files" in f["detail"]
        assert f["detail"]["dimension"] == "cross_module_architecture"

    def test_invalid_dimension_rejected(self):
        state = empty_state()
        findings_data = [
            {
                "dimension": "nonexistent_dimension",
                "identifier": "foo",
                "summary": "test",
                "confidence": "high",
            }
        ]

        diff = import_holistic_findings(findings_data, state, "python")

        assert diff["new"] == 0
        assert len(state["findings"]) == 0

    def test_missing_fields_rejected(self):
        state = empty_state()
        findings_data = [
            {"dimension": "cross_module_architecture"}
        ]  # missing identifier, summary, confidence

        diff = import_holistic_findings(findings_data, state, "python")

        assert diff["new"] == 0

    def test_multiple_findings(self):
        state = empty_state()
        findings_data = [
            {
                "dimension": "cross_module_architecture",
                "identifier": "god_module",
                "summary": "utils.py imported everywhere",
                "confidence": "high",
                "related_files": ["utils.py", "a.py"],
                "suggestion": "Split utils.py by domain",
            },
            {
                "dimension": "error_consistency",
                "identifier": "mixed_strategies",
                "summary": "Three error strategies across modules",
                "confidence": "medium",
                "related_files": ["handler.py", "service.py"],
                "suggestion": "Consolidate to Result type",
            },
        ]

        diff = import_holistic_findings(findings_data, state, "python")

        assert diff["new"] == 2
        assert len(state["findings"]) == 2

    def test_holistic_cache_updated(self):
        state = empty_state()
        findings_data = [
            {
                "dimension": "cross_module_architecture",
                "identifier": "god_module",
                "summary": "test finding",
                "confidence": "high",
                "suggestion": "split it",
            }
        ]

        import_holistic_findings(findings_data, state, "python")

        rc = state.get("review_cache", {})
        assert "holistic" in rc
        assert rc["holistic"]["finding_count"] == 1
        assert "reviewed_at" in rc["holistic"]

    def test_reviewed_files_refreshes_per_file_cache(self, tmp_path):
        state = empty_state()
        module_path = tmp_path / "pkg" / "module.py"
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text("def run():\n    return 1\n")

        findings_data = {
            "assessments": {"high_level_elegance": 95},
            "findings": [],
            "reviewed_files": ["pkg/module.py"],
        }

        from desloppify.core.runtime_state import RuntimeContext, runtime_scope
        ctx = RuntimeContext(project_root=tmp_path)
        with runtime_scope(ctx), \
             patch("desloppify.intelligence.review.importing.holistic.PROJECT_ROOT", tmp_path):
            _ = import_holistic_findings(findings_data, state, "python")

        files_cache = state.get("review_cache", {}).get("files", {})
        assert "pkg/module.py" in files_cache
        entry = files_cache["pkg/module.py"]
        assert entry.get("content_hash")
        assert entry.get("reviewed_at")

    def test_holistic_potential_added(self):
        state = empty_state()
        findings_data = [
            {
                "dimension": "dependency_health",
                "identifier": "unused_deps",
                "summary": "3 unused deps",
                "confidence": "medium",
                "suggestion": "Remove unused dependencies",
            }
        ]

        import_holistic_findings(findings_data, state, "python")

        pots = state.get("potentials", {})
        assert pots.get("python", {}).get("review") == HOLISTIC_POTENTIAL

    def test_finding_id_contains_holistic(self):
        state = empty_state()
        findings_data = [
            {
                "dimension": "cross_module_architecture",
                "identifier": "god_module",
                "summary": "test",
                "confidence": "high",
                "suggestion": "split it",
            }
        ]

        import_holistic_findings(findings_data, state, "python")

        fid = list(state["findings"].keys())[0]
        assert "holistic" in fid

    def test_positive_observation_skipped(self):
        """Positive observations (compliments) are rejected during import."""
        state = empty_state()
        findings_data = [
            {
                "dimension": "cross_module_architecture",
                "identifier": "good_decomposition",
                "summary": "Good decomposition of domain modules",
                "confidence": "high",
                "suggestion": "Keep it up",
            },
            {
                "dimension": "error_consistency",
                "identifier": "well_structured",
                "summary": "Well structured error handling throughout",
                "confidence": "high",
                "suggestion": "Continue this pattern",
            },
            {
                "dimension": "naming_quality",
                "identifier": "vague_name",
                "summary": "processData is vague — rename to reconcileInvoice",
                "confidence": "high",
                "suggestion": "Rename processData to reconcileInvoice",
            },
        ]

        diff = import_holistic_findings(findings_data, state, "python")

        # Only the actual defect should be imported
        assert diff["new"] == 1
        assert diff.get("skipped", 0) == 2
        findings = list(state["findings"].values())
        assert len(findings) == 1
        assert "vague_name" in findings[0]["id"]

    def test_missing_suggestion_rejected(self):
        """Findings without suggestion field are rejected."""
        state = empty_state()
        findings_data = [
            {
                "dimension": "cross_module_architecture",
                "identifier": "god_module",
                "summary": "utils.py imported everywhere",
                "confidence": "high",
                # Missing: suggestion
            },
        ]

        diff = import_holistic_findings(findings_data, state, "python")

        assert diff["new"] == 0
        assert diff.get("skipped", 0) == 1
        assert "suggestion" in diff["skipped_details"][0]["missing"]


# ===================================================================
# Scoring: holistic multiplier
# ===================================================================


class TestHolisticScoring:
    """Review findings are excluded from detection-side scoring.

    The review detector is scored via subjective assessments only.
    ``detector_pass_rate("review", ...)`` always returns a perfect score
    regardless of the findings present.
    """

    def _holistic_finding(self, confidence="high", status="open"):
        return {
            "detector": "review",
            "status": status,
            "confidence": confidence,
            "file": ".",
            "zone": "production",
            "detail": {"holistic": True},
        }

    def _file_finding(self, confidence="high", file="src/a.py", status="open"):
        return {
            "detector": "review",
            "status": status,
            "confidence": confidence,
            "file": file,
            "zone": "production",
            "detail": {},
        }

    def test_review_excluded_from_scoring(self):
        """Review findings always return perfect pass rate."""
        findings = {"0": self._holistic_finding(confidence="high")}
        rate, issues, weighted = detector_pass_rate("review", findings, 60)

        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_multiple_review_findings_still_excluded(self):
        """Multiple review findings still produce perfect score."""
        findings = {
            "0": self._holistic_finding(confidence="high"),
            "1": self._holistic_finding(confidence="medium"),
        }
        rate, issues, weighted = detector_pass_rate("review", findings, 60)

        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_mixed_holistic_and_file_excluded(self):
        """Both holistic and file-based review findings are excluded."""
        findings = {
            "0": self._holistic_finding(confidence="high"),
            "1": self._file_finding(confidence="high", file="src/a.py"),
            "2": self._file_finding(confidence="high", file="src/a.py"),
        }
        rate, issues, weighted = detector_pass_rate("review", findings, 60)

        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_resolved_review_also_excluded(self):
        """Even resolved review findings return perfect score."""
        findings = {"0": self._holistic_finding(confidence="high", status="fixed")}
        rate, issues, weighted = detector_pass_rate("review", findings, 60)

        assert issues == 0
        assert weighted == 0.0
        assert rate == 1.0


# ===================================================================
# path_scoped_findings includes holistic
# ===================================================================


class TestPathScopedFindings:
    def test_holistic_included_with_scan_path(self):
        findings = {
            "review::.::holistic::arch::abc": {
                "file": ".",
                "status": "open",
                "detector": "review",
                "detail": {"holistic": True},
            },
            "unused::src/a.py::foo": {
                "file": "src/a.py",
                "status": "open",
                "detector": "unused",
            },
            "unused::lib/b.py::bar": {
                "file": "lib/b.py",
                "status": "open",
                "detector": "unused",
            },
        }

        result = path_scoped_findings(findings, "src")

        # Should include holistic (file=".") and src/a.py, but not lib/b.py
        assert "review::.::holistic::arch::abc" in result
        assert "unused::src/a.py::foo" in result
        assert "unused::lib/b.py::bar" not in result

    def test_holistic_included_with_root_path(self):
        findings = {
            "review::.::holistic::test": {
                "file": ".",
                "status": "open",
            },
        }

        result = path_scoped_findings(findings, ".")
        assert len(result) == 1

    def test_holistic_included_with_no_path(self):
        findings = {
            "review::.::holistic::test": {
                "file": ".",
                "status": "open",
            },
        }

        result = path_scoped_findings(findings, None)
        assert len(result) == 1


# ===================================================================
# Holistic staleness detection
# ===================================================================


class TestHolisticStaleness:
    def test_no_cache_returns_unreviewed(self):
        entries = detect_holistic_review_staleness({}, total_files=100)
        assert len(entries) == 1
        assert entries[0]["name"] == "holistic_unreviewed"

    def test_fresh_cache_returns_empty(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cache = {
            "holistic": {
                "reviewed_at": now,
                "file_count_at_review": 100,
                "finding_count": 2,
            }
        }
        entries = detect_holistic_review_staleness(cache, total_files=100)
        assert len(entries) == 0

    def test_stale_cache_returns_stale(self):
        old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat(
            timespec="seconds"
        )
        cache = {
            "holistic": {
                "reviewed_at": old,
                "file_count_at_review": 100,
                "finding_count": 2,
            }
        }
        entries = detect_holistic_review_staleness(cache, total_files=100)
        assert len(entries) == 1
        assert entries[0]["name"] == "holistic_stale"
        assert "45 days" in entries[0]["summary"]

    def test_drift_returns_stale(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cache = {
            "holistic": {
                "reviewed_at": now,
                "file_count_at_review": 50,
                "finding_count": 2,
            }
        }
        # 50 → 80 = 60% drift, exceeds 20% threshold
        entries = detect_holistic_review_staleness(cache, total_files=80)
        assert len(entries) == 1
        assert entries[0]["name"] == "holistic_stale"
        assert "50" in entries[0]["summary"]
        assert "80" in entries[0]["summary"]

    def test_small_drift_returns_empty(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cache = {
            "holistic": {
                "reviewed_at": now,
                "file_count_at_review": 100,
                "finding_count": 2,
            }
        }
        # 100 → 110 = 10% drift, within 20% threshold
        entries = detect_holistic_review_staleness(cache, total_files=110)
        assert len(entries) == 0

    def test_unparseable_date_returns_stale(self):
        cache = {
            "holistic": {
                "reviewed_at": "not-a-date",
                "file_count_at_review": 100,
                "finding_count": 2,
            }
        }
        entries = detect_holistic_review_staleness(cache, total_files=100)
        assert len(entries) == 1
        assert entries[0]["name"] == "holistic_stale"


# ===================================================================
# Narrative: _count_open_by_detector holistic tracking
# ===================================================================


class TestNarrativeHolisticCounting:
    def test_review_holistic_counted_separately(self):
        findings = {
            "review::.::holistic::arch::abc": {
                "status": "open",
                "detector": "review",
                "detail": {"holistic": True},
            },
            "review::src/a.py::naming::def": {
                "status": "open",
                "detector": "review",
                "detail": {},
            },
        }

        by_det = _count_open_by_detector(findings)

        assert by_det["review"] == 2  # total review findings
        assert by_det["review_holistic"] == 1  # holistic subset

    def test_no_holistic_no_key(self):
        findings = {
            "review::src/a.py::naming::def": {
                "status": "open",
                "detector": "review",
                "detail": {},
            },
        }

        by_det = _count_open_by_detector(findings)

        assert by_det["review"] == 1
        assert "review_holistic" not in by_det

    def test_resolved_holistic_not_counted(self):
        findings = {
            "review::.::holistic::arch::abc": {
                "status": "fixed",
                "detector": "review",
                "detail": {"holistic": True},
            },
        }

        by_det = _count_open_by_detector(findings)

        assert by_det.get("review", 0) == 0
        assert by_det.get("review_holistic", 0) == 0


# ===================================================================
# Show display: "Codebase-wide" for file="."
# ===================================================================


# ===================================================================
# file_excerpt
# ===================================================================


class TestFileExcerpt:
    def test_short_file_returns_full(self, tmp_path):
        p = _make_file(str(tmp_path), "short.py", lines=10)
        excerpt = file_excerpt(p)
        assert excerpt is not None
        assert excerpt.count("\n") == 10

    def test_long_file_truncated(self, tmp_path):
        p = _make_file(str(tmp_path), "long.py", lines=100)
        excerpt = file_excerpt(p, max_lines=30)
        assert excerpt is not None
        assert "70 more lines" in excerpt
        # First 30 lines present
        assert "def func_0" in excerpt
        assert "def func_29" in excerpt

    def test_nonexistent_returns_none(self):
        assert file_excerpt("/nonexistent/file.py") is None

    def test_custom_max_lines(self, tmp_path):
        p = _make_file(str(tmp_path), "medium.py", lines=20)
        excerpt = file_excerpt(p, max_lines=5)
        assert "15 more lines" in excerpt


# ===================================================================
# extract_imported_names
# ===================================================================


class TestExtractImportedNames:
    def test_from_import(self):
        code = "from os.path import join, exists\n"
        names = extract_imported_names(code)
        assert "join" in names
        assert "exists" in names

    def test_plain_import(self):
        code = "import sys\nimport os\n"
        names = extract_imported_names(code)
        assert "sys" in names
        assert "os" in names

    def test_import_as(self):
        code = "from collections import Counter as Cnt\n"
        names = extract_imported_names(code)
        assert "Counter" in names  # Takes the original name

    def test_empty(self):
        code = "x = 1\ny = 2\n"
        names = extract_imported_names(code)
        assert len(names) == 0

    def test_mixed(self):
        code = "from foo import bar, baz\nimport qux\n"
        names = extract_imported_names(code)
        assert names == {"bar", "baz", "qux"}


# ===================================================================
# Sibling behavior analysis in build_holistic_context
# ===================================================================


class TestSiblingBehavior:
    def test_detects_outlier(self, tmp_path):
        """A file missing an import shared by >60% of siblings is flagged."""
        # 4 files in same dir, 3 import compute_narrative, 1 doesn't
        for i in range(3):
            _make_file(
                str(tmp_path),
                f"commands/cmd_{i}.py",
                content=f"from ..narrative import compute_narrative\ndef cmd_{i}(): pass\n",
            )
        _make_file(
            str(tmp_path), "commands/review/cmd.py", content="def cmd_review(): pass\n"
        )  # Missing compute_narrative
        files = [
            os.path.join(str(tmp_path), f"commands/{n}")
            for n in [f"cmd_{i}.py" for i in range(3)] + ["review/cmd.py"]
        ]
        lang = _mock_lang(files)
        state = empty_state()

        ctx = build_holistic_context(tmp_path, lang, state, files=files)

        sibling = ctx["conventions"].get("sibling_behavior", {})
        assert "commands/" in sibling
        outliers = sibling["commands/"]["outliers"]
        outlier_files = [o["file"] for o in outliers]
        assert any("review/cmd" in f for f in outlier_files)
        # compute_narrative should be in shared_patterns
        shared = sibling["commands/"]["shared_patterns"]
        assert "compute_narrative" in shared

    def test_no_outlier_when_all_share(self, tmp_path):
        """No outliers when all files import the same things."""
        for i in range(4):
            _make_file(
                str(tmp_path),
                f"lib/mod_{i}.py",
                content="from os.path import join\ndef f(): pass\n",
            )
        files = [os.path.join(str(tmp_path), f"lib/mod_{i}.py") for i in range(4)]
        lang = _mock_lang(files)
        state = empty_state()

        ctx = build_holistic_context(tmp_path, lang, state, files=files)

        sibling = ctx["conventions"].get("sibling_behavior", {})
        # join is shared by all, no outliers
        if "lib/" in sibling:
            assert len(sibling["lib/"]["outliers"]) == 0

    def test_too_few_siblings_skipped(self, tmp_path):
        """Directories with <3 files are skipped."""
        _make_file(str(tmp_path), "tiny/a.py", content="import sys\n")
        _make_file(str(tmp_path), "tiny/b.py", content="import os\n")
        files = [os.path.join(str(tmp_path), f"tiny/{n}.py") for n in ("a", "b")]
        lang = _mock_lang(files)
        state = empty_state()

        ctx = build_holistic_context(tmp_path, lang, state, files=files)

        sibling = ctx["conventions"].get("sibling_behavior", {})
        assert "tiny/" not in sibling


# ===================================================================
# File excerpts on god_modules and util_files
# ===================================================================


class TestExcerptsInContext:
    def test_god_module_has_excerpt(self, tmp_path):
        """God modules include an excerpt field."""
        f1 = _make_file(str(tmp_path), "core.py", lines=50)
        lang = _mock_lang([f1])
        # Build a dep graph that makes f1 a god module (>=5 importers)
        lang.dep_graph = {
            f1: {"importers": {f"mod_{i}" for i in range(6)}, "imports": set()},
        }
        state = empty_state()

        ctx = build_holistic_context(tmp_path, lang, state, files=[f1])

        god_mods = ctx["architecture"].get("god_modules", [])
        assert len(god_mods) >= 1
        assert "excerpt" in god_mods[0]
        assert "def func_0" in god_mods[0]["excerpt"]

    def test_util_file_has_excerpt(self, tmp_path):
        f1 = _make_file(str(tmp_path), "src/utils.py", lines=50)
        f2 = _make_file(str(tmp_path), "src/main.py", lines=20)
        lang = _mock_lang([f1, f2])
        state = empty_state()

        ctx = build_holistic_context(tmp_path, lang, state, files=[f1, f2])

        util_files = ctx["abstractions"]["util_files"]
        assert len(util_files) >= 1
        assert "excerpt" in util_files[0]
        assert "def func_0" in util_files[0]["excerpt"]


# ===================================================================
# _build_investigation_batches
# ===================================================================


class TestBuildInvestigationBatches:
    def test_returns_batches_from_rich_context(self):
        """Batches are built from holistic context data."""
        ctx = {
            "architecture": {
                "god_modules": [{"file": "core.py", "importers": 10, "excerpt": "..."}],
                "top_imported": {"core.py": 10},
            },
            "coupling": {
                "module_level_io": [
                    {"file": "init.py", "line": 5, "code": "open('f')"}
                ],
            },
            "conventions": {
                "sibling_behavior": {
                    "commands/": {
                        "shared_patterns": {
                            "compute_narrative": {"count": 6, "total": 7}
                        },
                        "outliers": [
                            {
                                "file": "commands/review/cmd.py",
                                "missing": ["compute_narrative"],
                            }
                        ],
                    }
                },
            },
            "errors": {
                "strategy_by_directory": {
                    "src/": {"try_catch": 5, "throws": 3, "returns_null": 2}
                }
            },
            "abstractions": {
                "util_files": [{"file": "utils.py", "loc": 200, "excerpt": "..."}]
            },
            "dependencies": {
                "existing_cycles": 1,
                "cycle_summaries": ["cycle in graph.py"],
            },
            "testing": {"critical_untested": [{"file": "scoring.py", "importers": 8}]},
            "api_surface": {"sync_async_mix": ["api.py"]},
            "structure": {},
        }
        lang = _mock_lang()

        batches = _build_investigation_batches(ctx, lang)

        assert len(batches) >= 1
        names = [b["name"] for b in batches]
        assert "Architecture & Coupling" in names
        assert "Conventions & Errors" in names

        # Check that files are populated
        arch_batch = next(b for b in batches if b["name"] == "Architecture & Coupling")
        assert "core.py" in arch_batch["files_to_read"]

        conv_batch = next(b for b in batches if b["name"] == "Conventions & Errors")
        assert "commands/review/cmd.py" in conv_batch["files_to_read"]

    def test_abstraction_batch_includes_hotspot_files(self):
        ctx = {
            "architecture": {},
            "coupling": {},
            "conventions": {},
            "errors": {"strategy_by_directory": {}},
            "abstractions": {
                "util_files": [],
                "pass_through_wrappers": [
                    {"file": "core/wrappers.py", "count": 4, "samples": ["a->b"]},
                ],
                "indirection_hotspots": [
                    {"file": "core/chains.py", "max_chain_depth": 4, "chain_count": 7},
                ],
                "wide_param_bags": [
                    {
                        "file": "core/options.py",
                        "wide_functions": 2,
                        "config_bag_mentions": 14,
                    },
                ],
                "one_impl_interfaces": [
                    {
                        "interface": "IWidget",
                        "declared_in": ["core/contracts.py"],
                        "implemented_in": ["core/widget_impl.py"],
                    }
                ],
            },
            "dependencies": {},
            "testing": {},
            "api_surface": {},
            "structure": {},
        }
        lang = _mock_lang()

        batches = _build_investigation_batches(ctx, lang)
        abstraction_batch = next(
            b for b in batches if b["name"] == "Abstractions & Dependencies"
        )

        assert "core/wrappers.py" in abstraction_batch["files_to_read"]
        assert "core/chains.py" in abstraction_batch["files_to_read"]
        assert "core/options.py" in abstraction_batch["files_to_read"]
        assert "core/contracts.py" in abstraction_batch["files_to_read"]
        assert "core/widget_impl.py" in abstraction_batch["files_to_read"]

    def test_empty_context_returns_no_batches(self):
        """No batches when context has no data."""
        ctx = {
            "architecture": {},
            "coupling": {},
            "conventions": {},
            "errors": {"strategy_by_directory": {}},
            "abstractions": {"util_files": []},
            "dependencies": {},
            "testing": {},
            "api_surface": {},
            "structure": {},
        }
        lang = _mock_lang()

        batches = _build_investigation_batches(ctx, lang)

        assert batches == []

    def test_batch_includes_all_available_files_by_default(self):
        """Thorough mode keeps full batch evidence unless caller sets a cap."""
        ctx = {
            "architecture": {
                "god_modules": [
                    {"file": f"mod_{i}.py", "importers": 10, "excerpt": ""}
                    for i in range(20)
                ],
            },
            "coupling": {},
            "conventions": {},
            "errors": {"strategy_by_directory": {}},
            "abstractions": {"util_files": []},
            "dependencies": {},
            "testing": {},
            "api_surface": {},
            "structure": {},
        }
        lang = _mock_lang()

        batches = _build_investigation_batches(ctx, lang)

        arch_batch = next(b for b in batches if b["name"] == "Architecture & Coupling")
        assert len(arch_batch["files_to_read"]) == 20

    def test_batch_has_required_fields(self):
        """Each batch has name, dimensions, files_to_read, why."""
        ctx = {
            "architecture": {
                "god_modules": [{"file": "core.py", "importers": 10, "excerpt": ""}],
            },
            "coupling": {},
            "conventions": {},
            "errors": {"strategy_by_directory": {}},
            "abstractions": {"util_files": []},
            "dependencies": {},
            "testing": {},
            "api_surface": {},
            "structure": {},
        }
        lang = _mock_lang()

        batches = _build_investigation_batches(ctx, lang)

        for batch in batches:
            assert "name" in batch
            assert "dimensions" in batch
            assert "files_to_read" in batch
            assert "why" in batch
            assert isinstance(batch["dimensions"], list)
            assert isinstance(batch["files_to_read"], list)

    def test_conventions_batch_maps_directory_signals_to_files(self):
        """Directory-level error strategy signals should map to concrete files."""
        ctx = {
            "architecture": {},
            "coupling": {},
            "conventions": {
                "sibling_behavior": {
                    "commands/": {
                        "shared_patterns": {"foo": {"count": 2, "total": 3}},
                        "outliers": [
                            {
                                "file": "commands/review/cmd.py",
                                "missing": ["foo"],
                            }
                        ],
                    }
                },
            },
            "errors": {
                "strategy_by_directory": {
                    "commands/": {"try_catch": 5, "throws": 4, "returns_null": 3},
                }
            },
            "abstractions": {"util_files": []},
            "dependencies": {},
            "testing": {},
            "api_surface": {},
            "structure": {
                "directory_profiles": {
                    "commands/": {
                        "file_count": 3,
                        "files": ["cmd.py", "scan_cmd.py", "plan_cmd.py"],
                    }
                }
            },
        }
        lang = _mock_lang()

        batches = _build_investigation_batches(ctx, lang)
        conv_batch = next(b for b in batches if b["name"] == "Conventions & Errors")

        assert "commands/review/cmd.py" in conv_batch["files_to_read"]
        assert "commands/scan_cmd.py" in conv_batch["files_to_read"]
        assert "commands/" not in conv_batch["files_to_read"]
        assert all(not path.endswith("/") for path in conv_batch["files_to_read"])

    def test_elegance_dimensions_are_batch_mapped(self):
        """Rich holistic context should expose high/mid/low elegance batch mappings."""
        ctx = {
            "architecture": {
                "god_modules": [{"file": "core.py", "importers": 10, "excerpt": "..."}],
            },
            "coupling": {},
            "conventions": {
                "sibling_behavior": {
                    "commands/": {
                        "shared_patterns": {
                            "compute_narrative": {"count": 6, "total": 7}
                        },
                        "outliers": [
                            {
                                "file": "commands/review/cmd.py",
                                "missing": ["compute_narrative"],
                            }
                        ],
                    }
                },
            },
            "errors": {
                "strategy_by_directory": {
                    "src/": {"try_catch": 5, "throws": 3, "returns_null": 2}
                }
            },
            "abstractions": {
                "util_files": [{"file": "utils.py", "loc": 200, "excerpt": "..."}]
            },
            "dependencies": {
                "existing_cycles": 1,
                "cycle_summaries": ["cycle in graph.py"],
            },
            "testing": {},
            "api_surface": {},
            "ai_debt_signals": {
                "file_signals": {"bloated.py": {"comment_ratio": 0.5}},
            },
            "migration_signals": {},
            "structure": {
                "root_files": [
                    {
                        "file": "visualize.py",
                        "loc": 300,
                        "fan_in": 1,
                        "fan_out": 3,
                        "role": "peripheral",
                    },
                ],
                "directory_profiles": {},
            },
        }
        lang = _mock_lang()

        batches = _build_investigation_batches(ctx, lang)
        mapped = {dim for batch in batches for dim in batch.get("dimensions", [])}

        assert "high_level_elegance" in mapped
        assert "mid_level_elegance" in mapped
        assert "low_level_elegance" in mapped


class TestFilterBatchesToDimensions:
    def test_fallback_batch_added_when_selected_dimension_unmapped(self):
        batches = [
            {
                "name": "Architecture & Coupling",
                "dimensions": ["cross_module_architecture"],
                "files_to_read": ["core.py", "utils.py"],
                "why": "god modules",
            }
        ]

        filtered = filter_batches_to_dimensions(batches, ["high_level_elegance"])

        assert len(filtered) == 1
        assert filtered[0]["name"] == "Cross-cutting Sweep"
        assert filtered[0]["dimensions"] == ["high_level_elegance"]
        assert filtered[0]["files_to_read"] == ["core.py", "utils.py"]

    def test_fallback_only_covers_missing_dimensions(self):
        batches = [
            {
                "name": "Architecture & Coupling",
                "dimensions": ["high_level_elegance"],
                "files_to_read": ["core.py"],
                "why": "god modules",
            }
        ]

        filtered = filter_batches_to_dimensions(
            batches,
            ["high_level_elegance", "low_level_elegance"],
        )

        assert len(filtered) == 2
        assert filtered[0]["name"] == "Architecture & Coupling"
        assert filtered[0]["dimensions"] == ["high_level_elegance"]
        assert filtered[1]["name"] == "Cross-cutting Sweep"
        assert filtered[1]["dimensions"] == ["low_level_elegance"]

    def test_fallback_filters_invalid_non_file_tokens(self):
        batches = [
            {
                "name": "Architecture & Coupling",
                "dimensions": ["high_level_elegance"],
                "files_to_read": ["core.py", "commands/", "services"],
                "why": "god modules",
            }
        ]

        filtered = filter_batches_to_dimensions(batches, ["low_level_elegance"])

        assert len(filtered) == 1
        assert filtered[0]["name"] == "Cross-cutting Sweep"
        assert filtered[0]["files_to_read"] == ["core.py"]


# ===================================================================
# prepare_holistic_review: workflow and batches in output
# ===================================================================


class TestPrepareHolisticReviewEnriched:
    def test_workflow_field_present(self, tmp_path):
        f1 = _make_file(str(tmp_path), "module.py", lines=50)
        lang = _mock_lang([f1])
        state = empty_state()

        data = prepare_holistic_review(tmp_path, lang, state, files=[f1])

        assert "workflow" in data
        assert isinstance(data["workflow"], list)
        assert len(data["workflow"]) == len(_HOLISTIC_WORKFLOW)
        assert "query.json" in data["workflow"][0]

    def test_investigation_batches_field_present(self, tmp_path):
        f1 = _make_file(str(tmp_path), "module.py", lines=50)
        lang = _mock_lang([f1])
        state = empty_state()

        data = prepare_holistic_review(tmp_path, lang, state, files=[f1])

        assert "investigation_batches" in data
        assert isinstance(data["investigation_batches"], list)

    def test_full_codebase_sweep_added_by_default(self, tmp_path):
        f1 = _make_file(str(tmp_path), "module_a.py", lines=50)
        f2 = _make_file(str(tmp_path), "module_b.py", lines=50)
        lang = _mock_lang([f1, f2])
        state = empty_state()

        data = prepare_holistic_review(tmp_path, lang, state, files=[f1, f2])

        full_sweep = next(
            b
            for b in data["investigation_batches"]
            if b["name"] == "Full Codebase Sweep"
        )
        assert len(full_sweep["files_to_read"]) == 2
        assert any(path.endswith("module_a.py") for path in full_sweep["files_to_read"])
        assert any(path.endswith("module_b.py") for path in full_sweep["files_to_read"])


# ===================================================================
# convention_outlier prompt update
# ===================================================================


class TestConventionOutlierPrompt:
    def test_sibling_behavior_in_look_for(self):
        prompt = DIMENSION_PROMPTS["convention_outlier"]
        look_for = " ".join(prompt["look_for"])
        assert "Sibling modules" in look_for
        assert "behavioral protocols" in look_for


# ===================================================================
# generate_remediation_plan
# ===================================================================


def _state_with_holistic_findings(*findings_args):
    """Create a state with holistic findings for plan testing."""
    state = empty_state()
    state["potentials"] = {"python": {"review": HOLISTIC_POTENTIAL}}
    state["objective_score"] = 45.0
    state["strict_score"] = 38.0
    for fid, conf, dim, summary in findings_args:
        state["findings"][fid] = {
            "id": fid,
            "file": ".",
            "status": "open",
            "detector": "review",
            "confidence": conf,
            "detail": {
                "holistic": True,
                "dimension": dim,
                "related_files": ["src/a.py", "src/b.py"],
                "evidence": ["evidence line 1"],
                "suggestion": "do the thing",
                "reasoning": "because reasons",
            },
            "summary": summary,
        }
    return state


class TestGenerateRemediationPlan:
    def test_basic_plan_content(self):
        state = _state_with_holistic_findings(
            (
                "review::.::holistic::arch::abc",
                "high",
                "cross_module_architecture",
                "God module found",
            ),
        )

        plan = generate_remediation_plan(state, "python")

        assert "# Holistic Review: Remediation Plan" in plan
        assert "God module found" in plan
        assert "cross module architecture" in plan
        assert "45.0/100" in plan
        assert "resolve fixed" in plan

    def test_priority_ordering_by_weight(self):
        state = _state_with_holistic_findings(
            (
                "review::.::holistic::test::low1",
                "low",
                "test_strategy",
                "Low impact thing",
            ),
            (
                "review::.::holistic::arch::high1",
                "high",
                "cross_module_architecture",
                "High impact thing",
            ),
        )

        plan = generate_remediation_plan(state, "python")

        # High confidence should come first (Priority 1)
        high_pos = plan.index("High impact thing")
        low_pos = plan.index("Low impact thing")
        assert high_pos < low_pos

    def test_score_impact_shown(self):
        state = _state_with_holistic_findings(
            (
                "review::.::holistic::arch::abc",
                "high",
                "cross_module_architecture",
                "Test finding",
            ),
        )

        plan = generate_remediation_plan(state, "python")

        # Should show estimated impact in pts
        assert "pts" in plan

    def test_resolve_command_included(self):
        fid = "review::.::holistic::arch::abc123"
        state = _state_with_holistic_findings(
            (fid, "high", "cross_module_architecture", "Finding X"),
        )

        plan = generate_remediation_plan(state, "python")

        assert f'resolve fixed "{fid}"' in plan

    def test_related_files_shown(self):
        state = _state_with_holistic_findings(
            (
                "review::.::holistic::arch::abc",
                "high",
                "cross_module_architecture",
                "Finding",
            ),
        )

        plan = generate_remediation_plan(state, "python")

        assert "`src/a.py`" in plan
        assert "`src/b.py`" in plan

    def test_re_evaluate_section(self):
        state = _state_with_holistic_findings(
            (
                "review::.::holistic::arch::abc",
                "high",
                "cross_module_architecture",
                "Finding",
            ),
        )

        plan = generate_remediation_plan(state, "python")

        assert "Re-evaluate" in plan
        assert "review --prepare" in plan
        assert "auto-resolve" in plan

    def test_how_to_use_section(self):
        state = _state_with_holistic_findings(
            (
                "review::.::holistic::arch::abc",
                "high",
                "cross_module_architecture",
                "Finding",
            ),
        )

        plan = generate_remediation_plan(state, "python")

        assert "How to use this plan" in plan
        assert "priority order" in plan

    def test_empty_findings_returns_clean_plan(self):
        state = empty_state()
        state["objective_score"] = 95.0

        plan = generate_remediation_plan(state, "python")

        assert "No open holistic findings" in plan
        assert "95.0/100" in plan

    def test_resolved_findings_excluded(self):
        state = _state_with_holistic_findings(
            (
                "review::.::holistic::arch::abc",
                "high",
                "cross_module_architecture",
                "Open one",
            ),
        )
        # Add a resolved finding that should NOT appear
        state["findings"]["review::.::holistic::test::def"] = {
            "id": "review::.::holistic::test::def",
            "file": ".",
            "status": "fixed",
            "detector": "review",
            "confidence": "high",
            "detail": {"holistic": True, "dimension": "test_strategy"},
            "summary": "Resolved finding",
        }

        plan = generate_remediation_plan(state, "python")

        assert "Open one" in plan
        assert "Resolved finding" not in plan

    def test_writes_to_file(self, tmp_path):
        state = _state_with_holistic_findings(
            (
                "review::.::holistic::arch::abc",
                "high",
                "cross_module_architecture",
                "Finding",
            ),
        )
        output = tmp_path / "plan.md"

        plan = generate_remediation_plan(state, "python", output_path=output)

        assert output.exists()
        assert output.read_text() == plan
        assert "Finding" in output.read_text()

    def test_lang_name_in_commands(self):
        state = _state_with_holistic_findings(
            (
                "review::.::holistic::arch::abc",
                "high",
                "cross_module_architecture",
                "Finding",
            ),
        )

        plan = generate_remediation_plan(state, "typescript")

        assert "--lang typescript" in plan


# ===================================================================
# New dimensions: authorization, ai_debt, migration (#57)
# ===================================================================


class TestNewHolisticDimensions:
    def test_authorization_consistency_prompt(self):
        assert "authorization_consistency" in DIMENSION_PROMPTS
        prompt = DIMENSION_PROMPTS["authorization_consistency"]
        assert "description" in prompt
        assert "look_for" in prompt
        assert "skip" in prompt

    def test_ai_generated_debt_prompt(self):
        assert "ai_generated_debt" in DIMENSION_PROMPTS
        prompt = DIMENSION_PROMPTS["ai_generated_debt"]
        assert "description" in prompt
        assert len(prompt["look_for"]) >= 3

    def test_incomplete_migration_prompt(self):
        assert "incomplete_migration" in DIMENSION_PROMPTS
        prompt = DIMENSION_PROMPTS["incomplete_migration"]
        assert "description" in prompt
        assert len(prompt["look_for"]) >= 3

    def test_new_dimensions_in_holistic_list(self):
        assert "authorization_consistency" in DIMENSIONS
        assert "ai_generated_debt" in DIMENSIONS
        assert "incomplete_migration" in DIMENSIONS

    def test_import_accepts_new_holistic_dimensions(self):
        state = empty_state()
        data = [
            {
                "dimension": "authorization_consistency",
                "identifier": "auth_gap",
                "summary": "Auth middleware missing on admin routes",
                "confidence": "high",
                "suggestion": "Add auth middleware to admin routes",
            },
            {
                "dimension": "ai_generated_debt",
                "identifier": "ai_comments",
                "summary": "Restating comments across 12 files",
                "confidence": "medium",
                "suggestion": "Remove restating comments",
            },
            {
                "dimension": "incomplete_migration",
                "identifier": "mixed_api",
                "summary": "Old axios + new fetch coexist in services/",
                "confidence": "high",
                "suggestion": "Consolidate to fetch",
            },
        ]
        diff = import_holistic_findings(data, state, "typescript")
        assert diff["new"] == 3

    def test_cross_module_prompt_includes_contract_drift_signal(self):
        look_for = DIMENSION_PROMPTS["cross_module_architecture"]["look_for"]
        joined = " ".join(look_for)
        assert "contracts drifting" in joined
        assert "Compatibility shim paths" in joined

    def test_high_level_prompt_includes_docs_runtime_alignment(self):
        look_for = DIMENSION_PROMPTS["high_level_elegance"]["look_for"]
        joined = " ".join(look_for)
        assert "reference docs match runtime reality" in joined


# ===================================================================
# New investigation batches: Authorization and AI Debt & Migrations
# ===================================================================


class TestNewInvestigationBatches:
    def test_authorization_batch_generated(self):
        """Batch 5 (Authorization) appears when auth context has gaps."""
        ctx = {
            "architecture": {},
            "coupling": {},
            "conventions": {},
            "errors": {"strategy_by_directory": {}},
            "abstractions": {"util_files": []},
            "dependencies": {},
            "testing": {},
            "api_surface": {},
            "structure": {},
            "authorization": {
                "route_auth_coverage": {
                    "routes/admin.py": {
                        "handlers": 5,
                        "with_auth": 2,
                        "without_auth": 3,
                    },
                },
                "service_role_usage": ["lib/supabase.ts"],
            },
        }
        lang = _mock_lang()

        batches = _build_investigation_batches(ctx, lang)

        names = [b["name"] for b in batches]
        assert "Authorization" in names
        auth_batch = next(b for b in batches if b["name"] == "Authorization")
        assert "routes/admin.py" in auth_batch["files_to_read"]
        assert "lib/supabase.ts" in auth_batch["files_to_read"]
        assert "authorization_consistency" in auth_batch["dimensions"]

    def test_ai_debt_migration_batch_generated(self):
        """Batch 6 (AI Debt & Migrations) appears when signals exist."""
        ctx = {
            "architecture": {},
            "coupling": {},
            "conventions": {},
            "errors": {"strategy_by_directory": {}},
            "abstractions": {"util_files": []},
            "dependencies": {},
            "testing": {},
            "api_surface": {},
            "structure": {},
            "ai_debt_signals": {
                "file_signals": {"bloated.py": {"comment_ratio": 0.5}},
            },
            "migration_signals": {
                "deprecated_markers": {
                    "total": 3,
                    "files": {"old_api.py": 2, "legacy.py": 1},
                },
                "migration_todos": [
                    {"file": "service.py", "text": "TODO: remove after migration"},
                ],
            },
        }
        lang = _mock_lang()

        batches = _build_investigation_batches(ctx, lang)

        names = [b["name"] for b in batches]
        assert "AI Debt & Migrations" in names
        debt_batch = next(b for b in batches if b["name"] == "AI Debt & Migrations")
        assert "bloated.py" in debt_batch["files_to_read"]
        assert "old_api.py" in debt_batch["files_to_read"]
        assert "service.py" in debt_batch["files_to_read"]
        assert "ai_generated_debt" in debt_batch["dimensions"]
        assert "incomplete_migration" in debt_batch["dimensions"]

    def test_no_auth_batch_when_no_gaps(self):
        """No Authorization batch when auth coverage has no gaps."""
        ctx = {
            "architecture": {},
            "coupling": {},
            "conventions": {},
            "errors": {"strategy_by_directory": {}},
            "abstractions": {"util_files": []},
            "dependencies": {},
            "testing": {},
            "api_surface": {},
            "structure": {},
            "authorization": {
                "route_auth_coverage": {
                    "routes/admin.py": {
                        "handlers": 5,
                        "with_auth": 5,
                        "without_auth": 0,
                    },
                },
            },
        }
        lang = _mock_lang()

        batches = _build_investigation_batches(ctx, lang)

        names = [b["name"] for b in batches]
        assert "Authorization" not in names

    def test_no_debt_batch_when_no_signals(self):
        """No AI Debt batch when no signals exist."""
        ctx = {
            "architecture": {},
            "coupling": {},
            "conventions": {},
            "errors": {"strategy_by_directory": {}},
            "abstractions": {"util_files": []},
            "dependencies": {},
            "testing": {},
            "api_surface": {},
            "structure": {},
        }
        lang = _mock_lang()

        batches = _build_investigation_batches(ctx, lang)

        names = [b["name"] for b in batches]
        assert "AI Debt & Migrations" not in names

    def test_up_to_seven_batches_possible(self):
        """With full context, up to 7 batches can be generated."""
        ctx = {
            "architecture": {
                "god_modules": [{"file": "core.py", "importers": 10, "excerpt": ""}],
            },
            "coupling": {
                "module_level_io": [
                    {"file": "init.py", "line": 5, "code": "open('f')"}
                ],
            },
            "conventions": {
                "sibling_behavior": {
                    "commands/": {
                        "shared_patterns": {
                            "compute_narrative": {"count": 6, "total": 7}
                        },
                        "outliers": [
                            {"file": "cmd.py", "missing": ["compute_narrative"]}
                        ],
                    }
                },
            },
            "errors": {
                "strategy_by_directory": {
                    "src/": {"try_catch": 5, "throws": 3, "returns_null": 2}
                }
            },
            "abstractions": {
                "util_files": [{"file": "utils.py", "loc": 200, "excerpt": ""}]
            },
            "dependencies": {
                "existing_cycles": 1,
                "cycle_summaries": ["cycle in graph.py"],
            },
            "testing": {"critical_untested": [{"file": "scoring.py", "importers": 8}]},
            "api_surface": {"sync_async_mix": ["api.py"]},
            "authorization": {
                "route_auth_coverage": {
                    "routes/admin.py": {
                        "handlers": 5,
                        "with_auth": 2,
                        "without_auth": 3,
                    },
                },
            },
            "ai_debt_signals": {
                "file_signals": {"bloated.py": {"comment_ratio": 0.5}},
            },
            "migration_signals": {
                "deprecated_markers": {"total": 1, "files": {"old.py": 1}},
            },
            "structure": {
                "root_files": [
                    {
                        "file": "viz.py",
                        "loc": 200,
                        "fan_in": 1,
                        "fan_out": 3,
                        "role": "peripheral",
                    },
                ],
                "directory_profiles": {
                    "commands/": {
                        "file_count": 8,
                        "files": ["scan.py", "show.py", "next.py"],
                        "total_loc": 1500,
                        "avg_fan_in": 2.0,
                        "avg_fan_out": 5.0,
                    },
                },
            },
        }
        lang = _mock_lang()

        batches = _build_investigation_batches(ctx, lang)

        assert len(batches) == 7
        names = [b["name"] for b in batches]
        assert "Architecture & Coupling" in names
        assert "Conventions & Errors" in names
        assert "Abstractions & Dependencies" in names
        assert "Testing & API" in names
        assert "Authorization" in names
        assert "AI Debt & Migrations" in names
        assert "Package Organization" in names

    def test_governance_batch_generated_when_reference_files_exist(self, tmp_path):
        for relpath in (
            "README.md",
            "DEVELOPMENT_PHILOSOPHY.md",
            "desloppify/README.md",
            "pyproject.toml",
        ):
            full_path = tmp_path / relpath
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text("reference")

        ctx = {
            "architecture": {
                "god_modules": [{"file": "core.py", "importers": 10, "excerpt": "..."}],
                "top_imported": {"core.py": 10},
            },
            "coupling": {},
            "conventions": {},
            "errors": {"strategy_by_directory": {}},
            "abstractions": {"util_files": []},
            "dependencies": {},
            "testing": {},
            "api_surface": {},
            "structure": {},
        }
        lang = _mock_lang()

        batches = _build_investigation_batches(ctx, lang, repo_root=tmp_path)

        names = [b["name"] for b in batches]
        assert "Governance & Contracts" in names
        governance = next(b for b in batches if b["name"] == "Governance & Contracts")
        assert "README.md" in governance["files_to_read"]
        assert "DEVELOPMENT_PHILOSOPHY.md" in governance["files_to_read"]
        assert "desloppify/README.md" in governance["files_to_read"]
        assert "pyproject.toml" in governance["files_to_read"]
        assert "core.py" in governance["files_to_read"]
        assert "high_level_elegance" in governance["dimensions"]
        assert "test_strategy" in governance["dimensions"]


# ===================================================================
# Structure context (section 12) — directory profiles, root files
# ===================================================================


class TestStructureContext:
    def test_structure_section_present(self, tmp_path):
        f1 = _make_file(str(tmp_path), "src/module_a.py", lines=50)
        f2 = _make_file(str(tmp_path), "src/module_b.py", lines=50)
        lang = _mock_lang([f1, f2])
        state = empty_state()

        ctx = build_holistic_context(tmp_path, lang, state, files=[f1, f2])

        assert "structure" in ctx
        structure = ctx["structure"]
        assert "directory_profiles" in structure

    def test_directory_profiles_computed(self, tmp_path):
        f1 = _make_file(str(tmp_path), "commands/scan.py", lines=100)
        f2 = _make_file(str(tmp_path), "commands/show.py", lines=80)
        f3 = _make_file(str(tmp_path), "commands/next.py", lines=60)
        files = [f1, f2, f3]
        lang = _mock_lang(files)
        state = empty_state()

        ctx = build_holistic_context(tmp_path, lang, state, files=files)

        profiles = ctx["structure"]["directory_profiles"]
        # Should have a profile for the commands directory
        matching = [k for k in profiles if "commands" in k]
        assert len(matching) >= 1
        profile = profiles[matching[0]]
        assert profile["file_count"] == 3
        assert profile["total_loc"] == 240  # 100+80+60

    def test_root_files_classified(self, tmp_path, patch_project_root):
        """Root-level files are classified as core (fan_in>=5) or peripheral."""
        patch_project_root(tmp_path)

        f1 = _make_file(str(tmp_path), "utils.py", lines=200)
        f2 = _make_file(str(tmp_path), "scorecard.py", lines=100)
        files = [f1, f2]
        lang = _mock_lang(files)
        # Make utils.py a god module, scorecard.py peripheral
        lang.dep_graph = {
            f1: {"importers": {f"mod_{i}" for i in range(10)}, "imports": set()},
            f2: {"importers": {"scan.py"}, "imports": set()},
        }
        state = empty_state()

        ctx = build_holistic_context(tmp_path, lang, state, files=files)

        root_files = ctx["structure"].get("root_files", [])
        assert len(root_files) == 2
        # utils.py should be core (10 importers), scorecard.py peripheral (1 importer)
        utils_entry = [rf for rf in root_files if "utils" in rf["file"]]
        scorecard_entry = [rf for rf in root_files if "scorecard" in rf["file"]]
        assert utils_entry[0]["role"] == "core"
        assert scorecard_entry[0]["role"] == "peripheral"

    def test_empty_files_returns_empty_structure(self, tmp_path):
        lang = _mock_lang([])
        state = empty_state()

        ctx = build_holistic_context(tmp_path, lang, state, files=[])

        assert ctx["structure"]["directory_profiles"] == {}


# ===================================================================
# Package Organization dimension
# ===================================================================


class TestPackageOrganizationDimension:
    def test_dimension_in_holistic_list(self):
        assert "package_organization" in DIMENSIONS

    def test_dimension_has_prompt(self):
        assert "package_organization" in DIMENSION_PROMPTS
        prompt = DIMENSION_PROMPTS["package_organization"]
        assert "description" in prompt
        assert "look_for" in prompt
        assert "skip" in prompt
        assert len(prompt["look_for"]) >= 4

    def test_import_accepts_package_organization(self):
        state = empty_state()
        data = [
            {
                "dimension": "package_organization",
                "identifier": "straggler_files",
                "summary": "3 viz files at root should be in output/ subpackage",
                "confidence": "high",
                "related_files": ["visualize.py", "scorecard.py", "_scorecard_draw.py"],
                "suggestion": "Move viz files into output/ subpackage",
            }
        ]
        diff = import_holistic_findings(data, state, "python")
        assert diff["new"] == 1

    def test_investigation_batch_generated(self):
        """Batch 7 (Package Organization) appears when structure context has peripheral files."""
        ctx = {
            "architecture": {},
            "coupling": {},
            "conventions": {},
            "errors": {"strategy_by_directory": {}},
            "abstractions": {"util_files": []},
            "dependencies": {},
            "testing": {},
            "api_surface": {},
            "structure": {
                "root_files": [
                    {
                        "file": "visualize.py",
                        "loc": 300,
                        "fan_in": 1,
                        "fan_out": 3,
                        "role": "peripheral",
                    },
                    {
                        "file": "scorecard.py",
                        "loc": 200,
                        "fan_in": 1,
                        "fan_out": 2,
                        "role": "peripheral",
                    },
                ],
                "directory_profiles": {
                    "commands/": {
                        "file_count": 8,
                        "files": ["scan.py", "show.py", "next.py"],
                        "total_loc": 1500,
                        "avg_fan_in": 2.0,
                        "avg_fan_out": 5.0,
                    },
                },
            },
        }
        lang = _mock_lang()

        batches = _build_investigation_batches(ctx, lang)

        names = [b["name"] for b in batches]
        assert "Package Organization" in names
        pkg_batch = next(b for b in batches if b["name"] == "Package Organization")
        assert "visualize.py" in pkg_batch["files_to_read"]
        assert "scorecard.py" in pkg_batch["files_to_read"]
        assert "package_organization" in pkg_batch["dimensions"]

    def test_no_batch_when_no_structure(self):
        """No Package Organization batch when structure context is empty."""
        ctx = {
            "architecture": {},
            "coupling": {},
            "conventions": {},
            "errors": {"strategy_by_directory": {}},
            "abstractions": {"util_files": []},
            "dependencies": {},
            "testing": {},
            "api_surface": {},
            "structure": {},
        }
        lang = _mock_lang()

        batches = _build_investigation_batches(ctx, lang)

        names = [b["name"] for b in batches]
        assert "Package Organization" not in names
