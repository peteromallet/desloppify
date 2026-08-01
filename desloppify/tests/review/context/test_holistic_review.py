"""Tests for holistic codebase-wide review support."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import desloppify.base.discovery.source as _discovery_source_mod
from desloppify.engine._scoring.detection import detector_pass_rate
from desloppify.engine._scoring.policy.core import HOLISTIC_POTENTIAL
from desloppify.engine.detectors.review_coverage import detect_holistic_review_staleness
from desloppify.intelligence.narrative.core import _count_open_by_detector
from desloppify.intelligence.review import (
    DIMENSION_PROMPTS,
    DIMENSIONS,
    HOLISTIC_DIMENSIONS_BY_LANG,
    REVIEW_SYSTEM_PROMPT,
    build_holistic_context,
)
from desloppify.intelligence.review import (
    import_holistic_issues as _import_holistic_issues_impl,
)
from desloppify.intelligence.review import (
    prepare_holistic_review as _prepare_holistic_review_impl,
)
from desloppify.intelligence.review._context.patterns import (
    extract_imported_names,
)
from desloppify.intelligence.review.context import file_excerpt
from desloppify.intelligence.review.prepare import HolisticReviewPrepareOptions
from desloppify.intelligence.review.prepare_batches_builders import (
    batch_concerns as _batch_concerns,
)
from desloppify.intelligence.review.prepare_batches_builders import (
    build_investigation_batches as _build_investigation_batches,
)
from desloppify.intelligence.review.prepare_batches_builders import (
    filter_batches_to_dimensions,
)
from desloppify.state import empty_state, path_scoped_issues


@pytest.fixture
def patch_project_root(monkeypatch):
    """Patch project root via RuntimeContext so all consumers see the override."""
    from desloppify.base.runtime_state import current_runtime_context

    ctx = current_runtime_context()

    def _patch(tmp_path):
        monkeypatch.setattr(ctx, "project_root", tmp_path)
        _discovery_source_mod.clear_source_file_cache_for_tests()

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


def _call_prepare_holistic_review(
    path,
    lang,
    state,
    *,
    dimensions=None,
    files=None,
    include_full_sweep=False,
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


def _call_import_holistic_issues(issues_data, state, lang_name, **kwargs):
    payload = issues_data if isinstance(issues_data, dict) else {"issues": issues_data}
    return _import_holistic_issues_impl(payload, state, lang_name, **kwargs)


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
        assert "root_cause_cluster" in REVIEW_SYSTEM_PROMPT


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

        data = _call_prepare_holistic_review(tmp_path, lang, state, files=[f1])

        assert len(data["dimensions"]) == len(DIMENSIONS)

    def test_python_gets_full_scorecard(self, tmp_path):
        f1 = _make_file(str(tmp_path), "module.py", lines=50)
        lang = _mock_lang([f1])
        state = empty_state()

        data = _call_prepare_holistic_review(tmp_path, lang, state, files=[f1])

        # Full scorecard: all 20 dimensions, not the curated subset
        assert len(data["dimensions"]) == 20
        assert "package_organization" in data["dimensions"]
        assert "api_surface_coherence" in data["dimensions"]
        assert "high_level_elegance" in data["dimensions"]
        assert "mid_level_elegance" in data["dimensions"]
        assert "low_level_elegance" in data["dimensions"]
        assert "design_coherence" in data["dimensions"]
        assert "initialization_coupling" in data["dimensions"]

    def test_typescript_gets_full_scorecard(self, tmp_path):
        f1 = _make_file(str(tmp_path), "module.ts", lines=50)
        lang = _mock_lang([f1])
        lang.name = "typescript"
        state = empty_state()

        data = _call_prepare_holistic_review(tmp_path, lang, state, files=[f1])

        # Full scorecard: all 20 dimensions, not the curated subset
        assert len(data["dimensions"]) == 20
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

        data = _call_prepare_holistic_review(tmp_path, lang, state, files=[f1])

        assert data["mode"] == "holistic"
        assert data["command"] == "review"
        # Full scorecard: all 20 dimensions (no longer filtered to curated subset)
        assert len(data["dimensions"]) == 20
        assert "holistic_context" in data
        assert "system_prompt" in data

    def test_custom_dimensions(self, tmp_path):
        f1 = _make_file(str(tmp_path), "module.py", lines=50)
        lang = _mock_lang([f1])
        state = empty_state()

        data = _call_prepare_holistic_review(
            tmp_path,
            lang,
            state,
            dimensions=["cross_module_architecture", "dependency_health"],
            files=[f1],
        )

        assert data["dimensions"] == ["cross_module_architecture", "dependency_health"]

    def test_concern_batch_respects_max_files(self):
        concerns = [
            SimpleNamespace(
                type="design_concern",
                file=f"src/file_{idx}.ts",
                summary=f"concern {idx}",
                question="is this intentional?",
                evidence=("Flagged by: structural, coupling",),
            )
            for idx in range(6)
        ]
        batch = _batch_concerns(concerns, max_files=3)

        assert batch is not None
        assert batch["name"] == "design_coherence"
        assert batch["dimensions"] == ["design_coherence"]
        assert "files_to_read" not in batch
        assert batch["concern_signal_count"] == 6
        assert len(batch["concern_signals"]) == 6
        assert batch["concern_signals"][0]["summary"] == "concern 0"
        assert batch["concern_signals"][0]["question"] == "is this intentional?"
        assert "mechanical detectors" in batch["why"]

    def test_concern_batch_includes_fingerprints_and_finding_ids(self):
        concerns = [
            SimpleNamespace(
                type="complexity_hotspot",
                file="src/big.ts",
                summary="Large file with high complexity",
                question="Is this file doing too many things?",
                evidence=("Flagged by: structural",),
                fingerprint="abc123def456",
                source_issues=("structural::big.ts::large_file", "structural::big.ts::high_complexity"),
            ),
            SimpleNamespace(
                type="systemic_smell",
                file="src/utils.ts",
                summary="Broad exception pattern",
                question="Is this intentional?",
                evidence=("Flagged by: smells",),
                fingerprint="xyz789",
                source_issues=("smells::utils.ts::broad_except",),
            ),
        ]
        batch = _batch_concerns(concerns)

        assert batch is not None
        signals = batch["concern_signals"]
        assert len(signals) == 2

        assert signals[0]["fingerprint"] == "abc123def456"
        assert signals[0]["finding_ids"] == [
            "structural::big.ts::large_file",
            "structural::big.ts::high_complexity",
        ]
        assert signals[1]["fingerprint"] == "xyz789"
        assert signals[1]["finding_ids"] == ["smells::utils.ts::broad_except"]

        # judgment_finding_counts should be keyed by detector (from source issue IDs)
        counts = batch["judgment_finding_counts"]
        assert counts["structural"] == 2
        assert counts["smells"] == 1

    def test_concern_batch_omits_empty_fingerprint_and_source_issues(self):
        concerns = [
            SimpleNamespace(
                type="design_concern",
                file="src/a.ts",
                summary="concern",
                question="ok?",
                evidence=(),
            ),
        ]
        batch = _batch_concerns(concerns)
        assert batch is not None
        signal = batch["concern_signals"][0]
        assert "fingerprint" not in signal
        assert "finding_ids" not in signal
        assert "judgment_finding_counts" not in batch

    def test_prepare_holistic_review_applies_max_files_to_concern_batch(
        self, tmp_path, monkeypatch
    ):
        tracked_files = [
            _make_file(str(tmp_path), f"src/file_{idx}.ts", lines=30)
            for idx in range(6)
        ]
        lang = _mock_lang(tracked_files)
        lang.name = "typescript"
        state = empty_state()

        concerns = [
            SimpleNamespace(type="design_concern", file=f"src/file_{idx}.ts")
            for idx in range(6)
        ]
        monkeypatch.setattr(
            "desloppify.engine._concerns.generators.generate_concerns",
            lambda *_args, **_kwargs: concerns,
        )

        data = _prepare_holistic_review_impl(
            tmp_path,
            lang,
            state,
            options=HolisticReviewPrepareOptions(
                dimensions=["design_coherence"],
                files=tracked_files,
                include_full_sweep=False,
                max_files_per_batch=2,
            ),
        )

        concern_batches = [
            batch
            for batch in data["investigation_batches"]
            if batch.get("dimensions") == ["design_coherence"]
        ]
        assert len(concern_batches) == 1
        concern_batch = concern_batches[0]
        # Concern signals are merged into the design_coherence batch
        assert concern_batch.get("concern_signal_count", 0) == 6

    def test_prepare_holistic_review_concerns_filtered_when_dim_inactive(
        self, tmp_path, monkeypatch
    ):
        """Concern batch (design_coherence) is filtered out when not in active dims."""
        tracked_files = [
            _make_file(str(tmp_path), f"src/file_{idx}.ts", lines=20)
            for idx in range(3)
        ]
        lang = _mock_lang(tracked_files)
        lang.name = "python"
        state = empty_state()

        concerns = [
            SimpleNamespace(
                type="mixed_responsibilities",
                file=f"src/file_{idx}.ts",
                summary="module does too much",
                question="should this module be split by responsibility?",
                evidence=("Flagged by: structural, responsibility_cohesion",),
            )
            for idx in range(3)
        ]
        monkeypatch.setattr(
            "desloppify.engine._concerns.generators.generate_concerns",
            lambda *_args, **_kwargs: concerns,
        )

        active_dims = [
            "cross_module_architecture",
            "high_level_elegance",
            "mid_level_elegance",
        ]
        data = _prepare_holistic_review_impl(
            tmp_path,
            lang,
            state,
            options=HolisticReviewPrepareOptions(
                dimensions=active_dims,
                files=tracked_files,
                include_full_sweep=False,
                max_files_per_batch=5,
            ),
        )

        # design_coherence is not in active_dims, so concern batch should be filtered out
        concern_batches = [
            batch
            for batch in data["investigation_batches"]
            if batch.get("dimensions") == ["design_coherence"]
        ]
        assert len(concern_batches) == 0

    def test_prepare_holistic_review_filters_out_of_scope_batch_files(
        self, tmp_path, monkeypatch
    ):
        in_scope_file = _make_file(str(tmp_path), "source/worker.py", lines=30)
        _make_file(str(tmp_path), "Wan2GP/wgp.py", lines=30)
        lang = _mock_lang([in_scope_file])
        lang.name = "python"
        state = empty_state()
        state["work_items"] = {
            "in_scope_structural": {
                "id": "in_scope_structural",
                "detector": "structural",
                "file": "source/worker.py",
                "status": "open",
                "summary": "structural in-scope",
                "detail": {"signals": {"loc": 200, "complexity_score": 8}},
            },
            "out_scope_structural": {
                "id": "out_scope_structural",
                "detector": "structural",
                "file": "Wan2GP/wgp.py",
                "status": "open",
                "summary": "structural out-of-scope",
                "detail": {"signals": {"loc": 900, "complexity_score": 20}},
            },
        }

        concerns = [
            SimpleNamespace(
                type="design_concern",
                file="source/worker.py",
                summary="in scope concern",
                question="question",
                evidence=("signal",),
            ),
            SimpleNamespace(
                type="design_concern",
                file="Wan2GP/wgp.py",
                summary="out-of-scope concern",
                question="question",
                evidence=("signal",),
            ),
        ]
        monkeypatch.setattr(
            "desloppify.engine._concerns.generators.generate_concerns",
            lambda *_args, **_kwargs: concerns,
        )

        data = _prepare_holistic_review_impl(
            tmp_path,
            lang,
            state,
            options=HolisticReviewPrepareOptions(
                dimensions=["design_coherence", "initialization_coupling"],
                files=[in_scope_file],
                include_full_sweep=False,
                max_files_per_batch=20,
            ),
        )

        # Batches no longer carry files_to_read; verify they exist and
        # concern signals are properly scoped.
        assert data["investigation_batches"]

        concern_signals = [
            signal
            for batch in data["investigation_batches"]
            for signal in batch.get("concern_signals", [])
        ]
        assert all(
            not str(signal.get("file", "")).startswith("Wan2GP/")
            for signal in concern_signals
        )


# ===================================================================
# import_holistic_issues
# ===================================================================


class TestImportHolisticIssues:
    def test_basic_import(self):
        state = empty_state()
        issues_data = [
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

        diff = _call_import_holistic_issues(issues_data, state, "python")

        assert diff["new"] == 1
        issues = list(state["work_items"].values())
        assert len(issues) == 1
        f = issues[0]
        assert f["file"] == "."
        assert f["detector"] == "review"
        assert f["detail"]["holistic"] is True
        assert "related_files" in f["detail"]
        assert f["detail"]["dimension"] == "cross_module_architecture"

    def test_invalid_dimension_rejected(self):
        state = empty_state()
        issues_data = [
            {
                "dimension": "nonexistent_dimension",
                "identifier": "foo",
                "summary": "test",
                "confidence": "high",
            }
        ]

        diff = _call_import_holistic_issues(issues_data, state, "python")

        assert diff["new"] == 0
        assert len(state["work_items"]) == 0

    def test_missing_fields_rejected(self):
        state = empty_state()
        issues_data = [
            {"dimension": "cross_module_architecture"}
        ]  # missing identifier, summary, confidence

        diff = _call_import_holistic_issues(issues_data, state, "python")

        assert diff["new"] == 0

    def test_multiple_issues(self):
        state = empty_state()
        issues_data = [
            {
                "dimension": "cross_module_architecture",
                "identifier": "god_module",
                "summary": "utils.py imported everywhere",
                "confidence": "high",
                "related_files": ["utils.py", "a.py"],
                "evidence": ["Utility module is imported by most entry points."],
                "suggestion": "Split utils.py by domain",
            },
            {
                "dimension": "error_consistency",
                "identifier": "mixed_strategies",
                "summary": "Three error strategies across modules",
                "confidence": "medium",
                "related_files": ["handler.py", "service.py"],
                "evidence": ["Handlers mix exceptions, sentinel values, and Result types."],
                "suggestion": "Consolidate to Result type",
            },
        ]

        diff = _call_import_holistic_issues(issues_data, state, "python")

        assert diff["new"] == 2
        assert len(state["work_items"]) == 2

    def test_holistic_cache_updated(self):
        state = empty_state()
        issues_data = [
            {
                "dimension": "cross_module_architecture",
                "identifier": "god_module",
                "summary": "test issue",
                "confidence": "high",
                "related_files": ["src/a.py"],
                "evidence": ["Single file coordinates unrelated responsibilities."],
                "suggestion": "split it",
            }
        ]

        _call_import_holistic_issues(issues_data, state, "python")

        rc = state.get("review_cache", {})
        assert "holistic" in rc
        assert rc["holistic"]["issue_count"] == 1
        assert "reviewed_at" in rc["holistic"]

    def test_public_facade_preserves_explicit_open_issue_ids(self):
        state = empty_state()
        issues_data = [
            {
                "dimension": "naming_quality",
                "identifier": "held_issue",
                "summary": "Legacy runtime loader reads like a predicate",
                "confidence": "high",
                "related_files": ["src/runtime.py"],
                "evidence": ["The loader name does not communicate its import side effect."],
                "suggestion": "Name the loader for its runtime-loading responsibility.",
            }
        ]

        _call_import_holistic_issues(issues_data, state, "python")
        held_id = next(iter(state["work_items"]))

        diff = _call_import_holistic_issues(
            {
                "issues": [],
                "review_scope": {"full_sweep_included": True},
            },
            state,
            "python",
            preserve_open_issue_ids={held_id},
        )

        assert diff["auto_resolved"] == 0
        assert state["work_items"][held_id]["status"] == "open"

    def test_reviewed_files_refreshes_per_file_cache(self, tmp_path):
        state = empty_state()
        module_path = tmp_path / "pkg" / "module.py"
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text("def run():\n    return 1\n")

        issues_data = {
            "assessments": {"high_level_elegance": 95},
            "issues": [],
            "reviewed_files": ["pkg/module.py"],
        }

        from desloppify.base.runtime_state import RuntimeContext, runtime_scope
        ctx = RuntimeContext(project_root=tmp_path)
        with runtime_scope(ctx):
            _ = _call_import_holistic_issues(issues_data, state, "python", project_root=tmp_path)

        files_cache = state.get("review_cache", {}).get("files", {})
        assert "pkg/module.py" in files_cache
        entry = files_cache["pkg/module.py"]
        assert entry.get("content_hash")
        assert entry.get("reviewed_at")

    def test_reviewed_files_auto_resolves_per_file_coverage_markers(self, tmp_path):
        """resolve_reviewed_file_coverage_issues is now a no-op.

        Dimension-level resolution is handled by resolve_holistic_coverage_issues
        which checks assessed dimensions in state.  This test verifies that
        importing a holistic review with an assessed dimension resolves the
        dimension-level subjective_review issue.
        """
        state = empty_state()

        coverage_id = "subjective_review::.::high_level_elegance"
        state["work_items"][coverage_id] = {
            "id": coverage_id,
            "detector": "subjective_review",
            "file": ".",
            "name": "high_level_elegance",
            "status": "open",
            "summary": "High elegance — no assessment on record",
            "detail": {"reason": "unassessed", "dimension": "high_level_elegance"},
            "tier": 4,
            "confidence": "low",
            "first_seen": "2026-01-01T00:00:00+00:00",
            "last_seen": "2026-01-01T00:00:00+00:00",
            "resolved_at": None,
            "reopen_count": 0,
            "note": None,
        }

        payload = {
            "assessments": {"high_level_elegance": 95},
            "issues": [],
        }

        from desloppify.base.runtime_state import RuntimeContext, runtime_scope

        ctx = RuntimeContext(project_root=tmp_path)
        with runtime_scope(ctx):
            diff = _call_import_holistic_issues(payload, state, "python", project_root=tmp_path)

        assert diff["auto_resolved"] >= 1
        assert state["work_items"][coverage_id]["status"] == "fixed"

    def test_holistic_potential_added(self):
        state = empty_state()
        issues_data = [
            {
                "dimension": "dependency_health",
                "identifier": "unused_deps",
                "summary": "3 unused deps",
                "confidence": "medium",
                "related_files": ["pyproject.toml"],
                "evidence": ["Declared dependencies have no import references."],
                "suggestion": "Remove unused dependencies",
            }
        ]

        _call_import_holistic_issues(issues_data, state, "python")

        pots = state.get("potentials", {})
        assert pots.get("python", {}).get("review") == HOLISTIC_POTENTIAL

    def test_issue_id_contains_holistic(self):
        state = empty_state()
        issues_data = [
            {
                "dimension": "cross_module_architecture",
                "identifier": "god_module",
                "summary": "test",
                "confidence": "high",
                "related_files": ["src/a.py"],
                "evidence": ["One module appears in many import chains."],
                "suggestion": "split it",
            }
        ]

        _call_import_holistic_issues(issues_data, state, "python")

        fid = list(state["work_items"].keys())[0]
        assert "holistic" in fid

    def test_positive_observation_skipped(self):
        """Positive observations (compliments) are rejected during import."""
        state = empty_state()
        issues_data = [
            {
                "dimension": "cross_module_architecture",
                "identifier": "good_decomposition",
                "summary": "Good decomposition of domain modules",
                "confidence": "high",
                "related_files": ["src/domain/a.py"],
                "evidence": ["Boundaries are explicit and layered cleanly."],
                "suggestion": "Keep it up",
            },
            {
                "dimension": "error_consistency",
                "identifier": "well_structured",
                "summary": "Well structured error handling throughout",
                "confidence": "high",
                "related_files": ["src/handlers/errors.py"],
                "evidence": ["Error paths are consistently normalized."],
                "suggestion": "Continue this pattern",
            },
            {
                "dimension": "naming_quality",
                "identifier": "vague_name",
                "summary": "processData is vague — rename to reconcileInvoice",
                "confidence": "high",
                "related_files": ["src/payments/service.py"],
                "evidence": ["Function name hides invoice reconciliation semantics."],
                "suggestion": "Rename processData to reconcileInvoice",
            },
        ]

        diff = _call_import_holistic_issues(issues_data, state, "python")

        # Only the actual defect should be imported
        assert diff["new"] == 1
        assert diff.get("skipped", 0) == 2
        issues = list(state["work_items"].values())
        assert len(issues) == 1
        assert "vague_name" in issues[0]["id"]

    def test_missing_suggestion_rejected(self):
        """Issues without suggestion field are rejected."""
        state = empty_state()
        issues_data = [
            {
                "dimension": "cross_module_architecture",
                "identifier": "god_module",
                "summary": "utils.py imported everywhere",
                "confidence": "high",
                "related_files": ["utils.py"],
                "evidence": ["Utility module is a fan-in bottleneck."],
                # Missing: suggestion
            },
        ]

        diff = _call_import_holistic_issues(issues_data, state, "python")

        assert diff["new"] == 0
        assert diff.get("skipped", 0) == 1
        assert "suggestion" in " ".join(diff["skipped_details"][0]["missing"])


# ===================================================================
# Scoring: holistic multiplier
# ===================================================================


class TestHolisticScoring:
    """Review issues are excluded from detection-side scoring.

    The review detector is scored via subjective assessments only.
    ``detector_pass_rate("review", ...)`` always returns a perfect score
    regardless of the issues present.
    """

    def _holistic_issue(self, confidence="high", status="open"):
        return {
            "detector": "review",
            "status": status,
            "confidence": confidence,
            "file": ".",
            "zone": "production",
            "detail": {"holistic": True},
        }

    def _file_issue(self, confidence="high", file="src/a.py", status="open"):
        return {
            "detector": "review",
            "status": status,
            "confidence": confidence,
            "file": file,
            "zone": "production",
            "detail": {},
        }

    def test_review_excluded_from_scoring(self):
        """Review issues always return perfect pass rate."""
        issues = {"0": self._holistic_issue(confidence="high")}
        rate, issues, weighted = detector_pass_rate("review", issues, 60)

        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_multiple_review_issues_still_excluded(self):
        """Multiple review issues still produce perfect score."""
        issues = {
            "0": self._holistic_issue(confidence="high"),
            "1": self._holistic_issue(confidence="medium"),
        }
        rate, issues, weighted = detector_pass_rate("review", issues, 60)

        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_mixed_holistic_and_file_excluded(self):
        """Both holistic and file-based review issues are excluded."""
        issues = {
            "0": self._holistic_issue(confidence="high"),
            "1": self._file_issue(confidence="high", file="src/a.py"),
            "2": self._file_issue(confidence="high", file="src/a.py"),
        }
        rate, issues, weighted = detector_pass_rate("review", issues, 60)

        assert rate == 1.0
        assert issues == 0
        assert weighted == 0.0

    def test_resolved_review_also_excluded(self):
        """Even resolved review issues return perfect score."""
        issues = {"0": self._holistic_issue(confidence="high", status="fixed")}
        rate, issues, weighted = detector_pass_rate("review", issues, 60)

        assert issues == 0
        assert weighted == 0.0
        assert rate == 1.0


# ===================================================================
# path_scoped_issues includes holistic
# ===================================================================


class TestPathScopedIssues:
    def test_holistic_included_with_scan_path(self):
        issues = {
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

        result = path_scoped_issues(issues, "src")

        # Should include holistic (file=".") and src/a.py, but not lib/b.py
        assert "review::.::holistic::arch::abc" in result
        assert "unused::src/a.py::foo" in result
        assert "unused::lib/b.py::bar" not in result

    def test_holistic_included_with_root_path(self):
        issues = {
            "review::.::holistic::test": {
                "file": ".",
                "status": "open",
            },
        }

        result = path_scoped_issues(issues, ".")
        assert len(result) == 1

    def test_holistic_included_with_no_path(self):
        issues = {
            "review::.::holistic::test": {
                "file": ".",
                "status": "open",
            },
        }

        result = path_scoped_issues(issues, None)
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
        now = datetime.now(UTC).isoformat(timespec="seconds")
        cache = {
            "holistic": {
                "reviewed_at": now,
                "file_count_at_review": 100,
                "issue_count": 2,
            }
        }
        entries = detect_holistic_review_staleness(cache, total_files=100)
        assert len(entries) == 0

    def test_stale_cache_returns_stale(self):
        old = (datetime.now(UTC) - timedelta(days=45)).isoformat(
            timespec="seconds"
        )
        cache = {
            "holistic": {
                "reviewed_at": old,
                "file_count_at_review": 100,
                "issue_count": 2,
            }
        }
        entries = detect_holistic_review_staleness(cache, total_files=100)
        assert len(entries) == 1
        assert entries[0]["name"] == "holistic_stale"
        assert "45 days" in entries[0]["summary"]

    def test_drift_returns_stale(self):
        now = datetime.now(UTC).isoformat(timespec="seconds")
        cache = {
            "holistic": {
                "reviewed_at": now,
                "file_count_at_review": 50,
                "issue_count": 2,
            }
        }
        # 50 → 80 = 60% drift, exceeds 20% threshold
        entries = detect_holistic_review_staleness(cache, total_files=80)
        assert len(entries) == 1
        assert entries[0]["name"] == "holistic_stale"
        assert "50" in entries[0]["summary"]
        assert "80" in entries[0]["summary"]

    def test_small_drift_returns_empty(self):
        now = datetime.now(UTC).isoformat(timespec="seconds")
        cache = {
            "holistic": {
                "reviewed_at": now,
                "file_count_at_review": 100,
                "issue_count": 2,
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
                "issue_count": 2,
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
        issues = {
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

        by_det = _count_open_by_detector(issues)

        assert by_det["review"] == 2  # total review issues
        assert by_det["review_holistic"] == 1  # holistic subset

    def test_no_holistic_no_key(self):
        issues = {
            "review::src/a.py::naming::def": {
                "status": "open",
                "detector": "review",
                "detail": {},
            },
        }

        by_det = _count_open_by_detector(issues)

        assert by_det["review"] == 1
        assert "review_holistic" not in by_det

    def test_resolved_holistic_not_counted(self):
        issues = {
            "review::.::holistic::arch::abc": {
                "status": "fixed",
                "detector": "review",
                "detail": {"holistic": True},
            },
        }

        by_det = _count_open_by_detector(issues)

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
            str(tmp_path), "commands/cmd_review.py", content="def cmd_review(): pass\n"
        )  # Missing compute_narrative — same directory as siblings
        files = [
            os.path.join(str(tmp_path), f"commands/{n}")
            for n in [f"cmd_{i}.py" for i in range(3)] + ["cmd_review.py"]
        ]
        lang = _mock_lang(files)
        state = empty_state()

        ctx = build_holistic_context(tmp_path, lang, state, files=files)

        sibling = ctx["conventions"].get("sibling_behavior", {})
        assert "commands/" in sibling
        outliers = sibling["commands/"]["outliers"]
        outlier_files = [o["file"] for o in outliers]
        assert any("cmd_review" in f for f in outlier_files)
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
        # Each batch is named by its single dimension
        assert "cross_module_architecture" in names
        assert "convention_outlier" in names

        # Batches no longer carry files_to_read — verify structure only
        arch_batch = next(b for b in batches if b["name"] == "cross_module_architecture")
        assert arch_batch["dimensions"] == ["cross_module_architecture"]
        assert "why" in arch_batch

        conv_batch = next(b for b in batches if b["name"] == "convention_outlier")
        assert conv_batch["dimensions"] == ["convention_outlier"]

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
            b for b in batches if b["name"] == "abstraction_fitness"
        )

        # Batches no longer carry files_to_read — verify batch exists with correct structure
        assert abstraction_batch["dimensions"] == ["abstraction_fitness"]
        assert "why" in abstraction_batch

    def test_empty_context_still_creates_dimension_batches(self):
        """Empty context still creates one batch per dimension (no files)."""
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

        assert len(batches) >= 1
        for batch in batches:
            assert "name" in batch
            assert "dimensions" in batch
            assert "files_to_read" not in batch

    def test_batches_created_without_files(self):
        """Batches are created per dimension without files_to_read."""
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

        arch_batch = next(b for b in batches if b["name"] == "cross_module_architecture")
        assert "files_to_read" not in arch_batch
        assert arch_batch["dimensions"] == ["cross_module_architecture"]

    def test_batch_has_required_fields(self):
        """Each batch has name, dimensions, why (but not files_to_read)."""
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
            assert "why" in batch
            assert isinstance(batch["dimensions"], list)
            assert "files_to_read" not in batch

    def test_conventions_batch_exists_for_convention_context(self):
        """Convention context should produce a convention_outlier batch."""
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
                        "files": ["cmd.py", "scan/cmd.py", "plan/cmd.py"],
                    }
                }
            },
        }
        lang = _mock_lang()

        batches = _build_investigation_batches(ctx, lang)
        conv_batch = next(b for b in batches if b["name"] == "convention_outlier")

        # Batches no longer carry files_to_read — verify structure
        assert conv_batch["dimensions"] == ["convention_outlier"]
        assert "why" in conv_batch

    def test_elegance_dimensions_are_batch_mapped(self):
        """Rich holistic context should expose high/mid/low elegance batch mappings."""
        ctx = {
            "architecture": {
                "god_modules": [{"file": "core.py", "importers": 10, "excerpt": "..."}],
            },
            "coupling": {
                "boundary_violations": [
                    {"file": "core.py", "detail": "crosses module boundary"}
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
                "name": "cross_module_architecture",
                "dimensions": ["cross_module_architecture"],
                "why": "god modules",
            }
        ]

        filtered = filter_batches_to_dimensions(batches, ["high_level_elegance"])

        assert len(filtered) == 1
        assert filtered[0]["name"] == "high_level_elegance"
        assert filtered[0]["dimensions"] == ["high_level_elegance"]
        # Fallback batches have no files_to_read
        assert "files_to_read" not in filtered[0]

    def test_fallback_only_covers_missing_dimensions(self):
        batches = [
            {
                "name": "high_level_elegance",
                "dimensions": ["high_level_elegance"],
                "why": "god modules",
            }
        ]

        filtered = filter_batches_to_dimensions(
            batches,
            ["high_level_elegance", "low_level_elegance"],
        )

        assert len(filtered) == 2
        assert filtered[0]["name"] == "high_level_elegance"
        assert filtered[0]["dimensions"] == ["high_level_elegance"]
        assert filtered[1]["name"] == "low_level_elegance"
        assert filtered[1]["dimensions"] == ["low_level_elegance"]

    def test_fallback_batch_created_for_missing_dimension(self):
        batches = [
            {
                "name": "high_level_elegance",
                "dimensions": ["high_level_elegance"],
                "why": "god modules",
            }
        ]

        filtered = filter_batches_to_dimensions(batches, ["low_level_elegance"])

        assert len(filtered) == 1
        assert filtered[0]["name"] == "low_level_elegance"
        assert filtered[0]["dimensions"] == ["low_level_elegance"]
        assert "files_to_read" not in filtered[0]
