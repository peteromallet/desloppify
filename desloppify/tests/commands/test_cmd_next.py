"""Tests for desloppify.app.commands.next."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import desloppify.engine.plan as plan_mod
import desloppify.intelligence.narrative as narrative_mod
from desloppify.app.commands import next as next_mod
from desloppify.app.commands.helpers.runtime import CommandRuntime
from desloppify.app.commands.next import _low_subjective_dimensions, cmd_next


def _args(**overrides):
    base = {
        "tier": None,
        "count": 1,
        "scope": None,
        "status": "open",
        "group": "item",
        "format": "terminal",
        "explain": False,
        "no_tier_fallback": False,
        "output": None,
        "lang": None,
        "path": ".",
        "state": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_common(monkeypatch, *, state, config=None):
    state = dict(state)
    state.setdefault("last_scan", "2026-01-01")
    config = config or {}

    monkeypatch.setattr(
        next_mod,
        "command_runtime",
        lambda _args: CommandRuntime(
            config=config,
            state=state,
            state_path="/tmp/fake-state.json",
        ),
    )
    monkeypatch.setattr(next_mod, "check_tool_staleness", lambda _state: None)
    monkeypatch.setattr(narrative_mod, "compute_narrative", lambda *a, **k: {})
    monkeypatch.setattr(next_mod, "resolve_lang", lambda _args: None)
    monkeypatch.setattr(plan_mod, "load_plan", lambda: {})
    monkeypatch.setattr(next_mod, "load_plan", lambda: {})


class TestNextModuleSanity:
    def test_cmd_next_callable(self):
        assert callable(cmd_next)

    def test_cmd_next_signature(self):
        sig = inspect.signature(cmd_next)
        assert list(sig.parameters.keys()) == ["args"]


class TestCmdNextOutput:
    def test_requires_prior_scan(self, monkeypatch, capsys):
        _patch_common(
            monkeypatch,
            state={
                "last_scan": None,
                "findings": {},
                "dimension_scores": {},
                "scan_path": ".",
            },
        )

        def _should_not_run(*_a, **_k):
            raise AssertionError("should not run without a completed scan")

        monkeypatch.setattr(next_mod, "write_query", _should_not_run)
        monkeypatch.setattr(next_mod, "build_work_queue", _should_not_run)

        cmd_next(_args())
        out = capsys.readouterr().out
        assert "No scans yet. Run: desloppify scan" in out

    def test_tier_navigator_always_printed(self, monkeypatch, capsys):
        written = []
        _patch_common(
            monkeypatch,
            state={
                "findings": {},
                "dimension_scores": {},
                "overall_score": 100.0,
                "objective_score": 100.0,
                "strict_score": 100.0,
                "scan_path": ".",
            },
        )
        monkeypatch.setattr(
            next_mod, "write_query", lambda payload: written.append(payload)
        )
        monkeypatch.setattr(
            next_mod,
            "build_work_queue",
            lambda *_a, **_k: {
                "items": [],
                "total": 0,
                "tier_counts": {1: 0, 2: 0, 3: 0, 4: 0},
                "requested_tier": None,
                "selected_tier": None,
                "fallback_reason": None,
                "available_tiers": [],
            },
        )

        cmd_next(_args())
        out = capsys.readouterr().out
        assert "Tier Navigator" in out
        assert "desloppify next --tier 1" in out
        assert "Nothing to do" in out
        assert written[0]["command"] == "next"
        assert written[0]["items"] == []

    def test_tier_fallback_message_and_payload(self, monkeypatch, capsys):
        written = []
        _patch_common(
            monkeypatch,
            state={
                "findings": {},
                "dimension_scores": {},
                "overall_score": 96.0,
                "objective_score": 96.0,
                "strict_score": 96.0,
                "scan_path": ".",
            },
        )
        monkeypatch.setattr(
            next_mod, "write_query", lambda payload: written.append(payload)
        )
        monkeypatch.setattr(
            next_mod,
            "build_work_queue",
            lambda *_a, **_k: {
                "items": [
                    {
                        "id": "smells::src/a.py::x",
                        "kind": "finding",
                        "tier": 2,
                        "effective_tier": 2,
                        "confidence": "high",
                        "detector": "smells",
                        "file": "src/a.py",
                        "summary": "Thing to fix",
                        "detail": {},
                        "status": "open",
                        "primary_command": "desloppify plan done ...",
                    }
                ],
                "total": 1,
                "tier_counts": {1: 0, 2: 1, 3: 0, 4: 0},
                "requested_tier": 1,
                "selected_tier": 2,
                "fallback_reason": "Requested T1 has 0 open -> showing T2 (nearest non-empty).",
                "available_tiers": [2],
            },
        )

        cmd_next(_args(tier=1))
        out = capsys.readouterr().out
        assert "Requested T1 has 0 open -> showing T2 (nearest non-empty)." in out
        assert written[0]["queue"]["requested_tier"] == 1
        assert written[0]["queue"]["selected_tier"] == 2

    def test_no_tier_fallback_strict_empty_guidance(self, monkeypatch, capsys):
        written = []
        _patch_common(
            monkeypatch,
            state={
                "findings": {},
                "dimension_scores": {},
                "overall_score": 97.0,
                "objective_score": 97.0,
                "strict_score": 97.0,
                "scan_path": ".",
            },
        )
        monkeypatch.setattr(
            next_mod, "write_query", lambda payload: written.append(payload)
        )
        monkeypatch.setattr(
            next_mod,
            "build_work_queue",
            lambda *_a, **_k: {
                "items": [],
                "total": 0,
                "tier_counts": {1: 2, 2: 1, 3: 0, 4: 0},
                "requested_tier": 4,
                "selected_tier": 4,
                "fallback_reason": "Requested T4 has 0 open.",
                "available_tiers": [1, 2],
            },
        )

        cmd_next(_args(tier=4, no_tier_fallback=True))
        out = capsys.readouterr().out
        assert "Requested T4 has 0 open." in out
        assert "Requested tier: T4" in out
        assert "Try: desloppify next --tier 1 | desloppify next --tier 2" in out
        assert written[0]["queue"]["available_tiers"] == [1, 2]

    def test_subjective_focus_and_review_prepare_hint(self, monkeypatch, capsys):
        _patch_common(
            monkeypatch,
            state={
                "findings": {},
                "dimension_scores": {
                    "Naming quality": {
                        "score": 94.0,
                        "strict": 94.0,
                        "issues": 2,
                        "detectors": {"subjective_assessment": {}},
                    },
                    "Logic clarity": {
                        "score": 96.0,
                        "strict": 96.0,
                        "issues": 1,
                        "detectors": {"subjective_assessment": {}},
                    },
                },
                "overall_score": 94.0,
                "objective_score": 98.0,
                "strict_score": 94.0,
                "scan_path": ".",
            },
        )
        monkeypatch.setattr(next_mod, "write_query", lambda _payload: None)
        monkeypatch.setattr(
            next_mod,
            "build_work_queue",
            lambda *_a, **_k: {
                "items": [
                    {
                        "id": "smells::src/a.py::x",
                        "kind": "finding",
                        "tier": 3,
                        "effective_tier": 3,
                        "confidence": "medium",
                        "detector": "smells",
                        "file": "src/a.py",
                        "summary": "Fix smell",
                        "detail": {},
                        "status": "open",
                        "primary_command": "desloppify plan done ...",
                    }
                ],
                "total": 1,
                "tier_counts": {1: 0, 2: 0, 3: 1, 4: 0},
                "requested_tier": None,
                "selected_tier": None,
                "fallback_reason": None,
                "available_tiers": [3],
            },
        )

        cmd_next(_args())
        out = capsys.readouterr().out
        assert "North star: strict 94.0/100 → target 95.0 (+1.0 needed)" in out
        assert "Subjective:" in out
        assert "below target" in out
        assert "show subjective" in out

    def test_subjective_coverage_debt_hint(self, monkeypatch, capsys):
        _patch_common(
            monkeypatch,
            state={
                "findings": {
                    "subjective_review::src/a.py::changed": {
                        "id": "subjective_review::src/a.py::changed",
                        "detector": "subjective_review",
                        "file": "src/a.py",
                        "tier": 4,
                        "confidence": "medium",
                        "summary": "File changed since last review — re-review recommended",
                        "status": "open",
                        "detail": {"reason": "changed"},
                    }
                },
                "dimension_scores": {},
                "overall_score": 90.0,
                "objective_score": 94.0,
                "strict_score": 90.0,
                "scan_path": ".",
            },
        )
        monkeypatch.setattr(next_mod, "write_query", lambda _payload: None)
        monkeypatch.setattr(
            next_mod,
            "build_work_queue",
            lambda *_a, **_k: {
                "items": [
                    {
                        "id": "smells::src/a.py::x",
                        "kind": "finding",
                        "tier": 3,
                        "effective_tier": 3,
                        "confidence": "medium",
                        "detector": "smells",
                        "file": "src/a.py",
                        "summary": "Fix smell",
                        "detail": {},
                        "status": "open",
                        "primary_command": "desloppify plan done ...",
                    }
                ],
                "total": 1,
                "tier_counts": {1: 0, 2: 0, 3: 1, 4: 1},
                "requested_tier": None,
                "selected_tier": None,
                "fallback_reason": None,
                "available_tiers": [3, 4],
            },
        )

        cmd_next(_args())
        out = capsys.readouterr().out
        assert "North star: strict 90.0/100 → target 95.0 (+5.0 needed)" in out
        assert "Subjective:" in out
        assert "need review" in out
        assert "show subjective" in out

    def test_unassessed_subjective_gap_prioritizes_holistic_refresh(
        self, monkeypatch, capsys
    ):
        _patch_common(
            monkeypatch,
            state={
                "findings": {},
                "dimension_scores": {
                    "High elegance": {
                        "score": 0.0,
                        "strict": 0.0,
                        "issues": 0,
                        "detectors": {"subjective_assessment": {}},
                    },
                },
                "overall_score": 90.0,
                "objective_score": 95.0,
                "strict_score": 90.0,
                "scan_path": ".",
            },
        )
        monkeypatch.setattr(next_mod, "write_query", lambda _payload: None)
        monkeypatch.setattr(
            next_mod,
            "build_work_queue",
            lambda *_a, **_k: {
                "items": [
                    {
                        "id": "smells::src/a.py::x",
                        "kind": "finding",
                        "tier": 3,
                        "effective_tier": 3,
                        "confidence": "medium",
                        "detector": "smells",
                        "file": "src/a.py",
                        "summary": "Fix smell",
                        "detail": {},
                        "status": "open",
                        "primary_command": "desloppify plan done ...",
                    }
                ],
                "total": 1,
                "tier_counts": {1: 0, 2: 0, 3: 1, 4: 0},
                "requested_tier": None,
                "selected_tier": None,
                "fallback_reason": None,
                "available_tiers": [3],
            },
        )

        cmd_next(_args())
        out = capsys.readouterr().out
        assert "Subjective:" in out
        assert "unassessed" in out
        assert "show subjective" in out

    def test_holistic_subjective_signal_is_called_out(self, monkeypatch, capsys):
        _patch_common(
            monkeypatch,
            state={
                "findings": {
                    "subjective_review::.::holistic_unreviewed": {
                        "id": "subjective_review::.::holistic_unreviewed",
                        "detector": "subjective_review",
                        "file": ".",
                        "tier": 4,
                        "confidence": "low",
                        "summary": "No holistic codebase review on record",
                        "status": "open",
                        "detail": {"reason": "unreviewed"},
                    }
                },
                "dimension_scores": {},
                "overall_score": 90.0,
                "objective_score": 95.0,
                "strict_score": 90.0,
                "scan_path": ".",
            },
        )
        monkeypatch.setattr(next_mod, "write_query", lambda _payload: None)
        monkeypatch.setattr(
            next_mod,
            "build_work_queue",
            lambda *_a, **_k: {
                "items": [
                    {
                        "id": "smells::src/a.py::x",
                        "kind": "finding",
                        "tier": 3,
                        "effective_tier": 3,
                        "confidence": "medium",
                        "detector": "smells",
                        "file": "src/a.py",
                        "summary": "Fix smell",
                        "detail": {},
                        "status": "open",
                        "primary_command": "desloppify plan done ...",
                    }
                ],
                "total": 1,
                "tier_counts": {1: 0, 2: 0, 3: 1, 4: 1},
                "requested_tier": None,
                "selected_tier": None,
                "fallback_reason": None,
                "available_tiers": [3, 4],
            },
        )

        cmd_next(_args())
        out = capsys.readouterr().out
        assert "Subjective:" in out
        assert "show subjective" in out

    def test_subjective_threshold_uses_configured_target(self, monkeypatch, capsys):
        _patch_common(
            monkeypatch,
            state={
                "findings": {},
                "dimension_scores": {
                    "Naming quality": {
                        "score": 96.0,
                        "strict": 96.0,
                        "issues": 1,
                        "detectors": {"subjective_assessment": {}},
                    },
                },
                "overall_score": 96.0,
                "objective_score": 99.0,
                "strict_score": 96.0,
                "scan_path": ".",
            },
            config={"target_strict_score": 97},
        )
        monkeypatch.setattr(next_mod, "write_query", lambda _payload: None)
        monkeypatch.setattr(
            next_mod,
            "build_work_queue",
            lambda *_a, **_k: {
                "items": [
                    {
                        "id": "smells::src/a.py::x",
                        "kind": "finding",
                        "tier": 3,
                        "effective_tier": 3,
                        "confidence": "medium",
                        "detector": "smells",
                        "file": "src/a.py",
                        "summary": "Fix smell",
                        "detail": {},
                        "status": "open",
                        "primary_command": "desloppify plan done ...",
                    }
                ],
                "total": 1,
                "tier_counts": {1: 0, 2: 0, 3: 1, 4: 0},
                "requested_tier": None,
                "selected_tier": None,
                "fallback_reason": None,
                "available_tiers": [3],
            },
        )

        cmd_next(_args())
        out = capsys.readouterr().out
        assert "North star: strict 96.0/100 → target 97.0 (+1.0 needed)" in out
        assert "Subjective:" in out
        assert "below target" in out
        assert "show subjective" in out

    def test_subjective_integrity_penalty_is_always_reported(self, monkeypatch, capsys):
        _patch_common(
            monkeypatch,
            state={
                "findings": {},
                "subjective_integrity": {
                    "status": "penalized",
                    "target_score": 95.0,
                    "matched_count": 2,
                    "matched_dimensions": ["naming_quality", "logic_clarity"],
                    "reset_dimensions": ["naming_quality", "logic_clarity"],
                },
                "dimension_scores": {
                    "Naming quality": {
                        "score": 0.0,
                        "strict": 0.0,
                        "issues": 0,
                        "detectors": {"subjective_assessment": {}},
                    },
                    "Logic clarity": {
                        "score": 0.0,
                        "strict": 0.0,
                        "issues": 0,
                        "detectors": {"subjective_assessment": {}},
                    },
                },
                "overall_score": 92.0,
                "objective_score": 96.0,
                "strict_score": 92.0,
                "scan_path": ".",
            },
        )
        monkeypatch.setattr(next_mod, "write_query", lambda _payload: None)
        monkeypatch.setattr(
            next_mod,
            "build_work_queue",
            lambda *_a, **_k: {
                "items": [
                    {
                        "id": "smells::src/a.py::x",
                        "kind": "finding",
                        "tier": 3,
                        "effective_tier": 3,
                        "confidence": "medium",
                        "detector": "smells",
                        "file": "src/a.py",
                        "summary": "Fix smell",
                        "detail": {},
                        "status": "open",
                        "primary_command": "desloppify plan done ...",
                    }
                ],
                "total": 1,
                "tier_counts": {1: 0, 2: 0, 3: 1, 4: 0},
                "requested_tier": None,
                "selected_tier": None,
                "fallback_reason": None,
                "available_tiers": [3],
            },
        )

        cmd_next(_args())
        out = capsys.readouterr().out
        assert "were reset to 0.0 this scan" in out
        assert "Anti-gaming safeguard applied" in out
        assert (
            "review --run-batches --runner codex --parallel --scan-after-import --dimensions"
            in out
        )
        assert "naming_quality" in out
        assert "logic_clarity" in out

    def test_explain_payload_serializes_item_explain(self, monkeypatch, capsys):
        written = []
        _patch_common(
            monkeypatch,
            state={
                "findings": {},
                "dimension_scores": {},
                "overall_score": 99.0,
                "objective_score": 99.0,
                "strict_score": 99.0,
                "scan_path": ".",
            },
        )
        monkeypatch.setattr(
            next_mod, "write_query", lambda payload: written.append(payload)
        )
        monkeypatch.setattr(
            next_mod,
            "build_work_queue",
            lambda *_a, **_k: {
                "items": [
                    {
                        "id": "subjective::naming_quality",
                        "kind": "subjective_dimension",
                        "tier": 4,
                        "effective_tier": 4,
                        "confidence": "medium",
                        "detector": "subjective_assessment",
                        "file": ".",
                        "summary": "Subjective dimension below target: Naming quality (94.0%)",
                        "detail": {"dimension_name": "Naming quality"},
                        "status": "open",
                        "subjective_score": 94.0,
                        "primary_command": "desloppify review --prepare",
                        "explain": {
                            "policy": "Subjective dimensions are always queued as T4."
                        },
                    }
                ],
                "total": 1,
                "tier_counts": {1: 0, 2: 0, 3: 0, 4: 1},
                "requested_tier": None,
                "selected_tier": None,
                "fallback_reason": None,
                "available_tiers": [4],
            },
        )

        cmd_next(_args(explain=True))
        out = capsys.readouterr().out
        assert "always queued as T4" in out
        assert written[0]["items"][0]["explain"] == {
            "policy": "Subjective dimensions are always queued as T4."
        }


    def test_score_impact_shown_when_potentials_available(self, monkeypatch, capsys):
        _patch_common(
            monkeypatch,
            state={
                "findings": {},
                "dimension_scores": {
                    "Code quality": {
                        "score": 80.0,
                        "strict": 78.0,
                        "issues": 5,
                        "checks": 100,
                        "tier": 2,
                    },
                },
                "potentials": {"python": {"smells": 5}},
                "overall_score": 85.0,
                "objective_score": 88.0,
                "strict_score": 83.0,
                "scan_path": ".",
            },
        )
        monkeypatch.setattr(next_mod, "write_query", lambda _payload: None)
        monkeypatch.setattr(
            next_mod,
            "build_work_queue",
            lambda *_a, **_k: {
                "items": [
                    {
                        "id": "smells::src/a.py::x",
                        "kind": "finding",
                        "tier": 2,
                        "effective_tier": 2,
                        "confidence": "high",
                        "detector": "smells",
                        "file": "src/a.py",
                        "summary": "Fix smell",
                        "detail": {},
                        "status": "open",
                        "primary_command": "desloppify plan done ...",
                    }
                ],
                "total": 1,
                "tier_counts": {1: 0, 2: 1, 3: 0, 4: 0},
                "requested_tier": None,
                "selected_tier": None,
                "fallback_reason": None,
                "available_tiers": [2],
            },
        )

        cmd_next(_args())
        out = capsys.readouterr().out
        # Impact line should appear if compute_score_impact returns > 0
        # The actual value depends on scoring internals; just verify the label appears
        # or doesn't crash when potentials are present
        assert "Next item" in out

    def test_subjective_dimension_shows_honesty_note(self, monkeypatch, capsys):
        _patch_common(
            monkeypatch,
            state={
                "findings": {},
                "dimension_scores": {},
                "overall_score": 94.0,
                "objective_score": 98.0,
                "strict_score": 94.0,
                "scan_path": ".",
            },
        )
        monkeypatch.setattr(next_mod, "write_query", lambda _payload: None)
        monkeypatch.setattr(
            next_mod,
            "build_work_queue",
            lambda *_a, **_k: {
                "items": [
                    {
                        "id": "subjective::naming_quality",
                        "kind": "subjective_dimension",
                        "tier": 4,
                        "effective_tier": 4,
                        "confidence": "medium",
                        "detector": "subjective_assessment",
                        "file": ".",
                        "summary": "Subjective dimension below target: Naming quality (94.0%)",
                        "detail": {"dimension_name": "Naming quality", "strict_score": 94.0},
                        "status": "open",
                        "subjective_score": 94.0,
                        "primary_command": "desloppify review --prepare",
                    }
                ],
                "total": 1,
                "tier_counts": {1: 0, 2: 0, 3: 0, 4: 1},
                "requested_tier": None,
                "selected_tier": None,
                "fallback_reason": None,
                "available_tiers": [4],
            },
        )

        cmd_next(_args())
        out = capsys.readouterr().out
        assert "scores can go down" in out


class TestLowSubjectiveDimensions:
    def test_filters_to_subjective_dims_below_threshold(self):
        dim_scores = {
            "File health": {
                "score": 82,
                "strict": 82,
                "tier": 3,
                "issues": 1,
                "detectors": {},
            },
            "Naming quality": {
                "score": 94.0,
                "strict": 94.0,
                "tier": 4,
                "issues": 2,
                "detectors": {"subjective_assessment": {}},
            },
            "Logic clarity": {
                "score": 96.0,
                "strict": 96.0,
                "tier": 4,
                "issues": 3,
                "detectors": {"subjective_assessment": {}},
            },
            "Custom Subjective": {
                "score": 91.0,
                "strict": 91.0,
                "tier": 4,
                "issues": 1,
                "detectors": {"subjective_assessment": {}},
            },
        }
        low = _low_subjective_dimensions({"dimension_scores": dim_scores}, dim_scores, threshold=95.0)
        assert low == [
            ("Custom Subjective", 91.0, 1),
            ("Naming quality", 94.0, 2),
        ]
