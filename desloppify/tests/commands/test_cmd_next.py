"""Tests for desloppify.app.commands.next."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import desloppify.intelligence.narrative as narrative_mod
import desloppify.utils as utils_mod
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
    monkeypatch.setattr(utils_mod, "check_tool_staleness", lambda _state: None)
    monkeypatch.setattr(narrative_mod, "compute_narrative", lambda *a, **k: {})
    monkeypatch.setattr(next_mod, "resolve_lang", lambda _args: None)


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
                        "primary_command": "desloppify resolve fixed ...",
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
                    "Naming Quality": {
                        "score": 94.0,
                        "strict": 94.0,
                        "issues": 2,
                        "detectors": {"subjective_assessment": {}},
                    },
                    "Logic Clarity": {
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
                        "primary_command": "desloppify resolve fixed ...",
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
        assert "Subjective quality (<95%): Naming Quality 94.0%" in out
        assert "review --prepare --dimensions naming_quality" in out

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
                        "primary_command": "desloppify resolve fixed ...",
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
        assert "Subjective coverage debt: 1 file (1 changed)" in out
        assert "show subjective_review --status open" in out

    def test_unassessed_subjective_gap_prioritizes_holistic_refresh(
        self, monkeypatch, capsys
    ):
        _patch_common(
            monkeypatch,
            state={
                "findings": {},
                "dimension_scores": {
                    "High Elegance": {
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
                        "primary_command": "desloppify resolve fixed ...",
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
        assert "Subjective integrity gap:" in out
        assert "Priority: `desloppify review --prepare --holistic --refresh`" in out
        assert "Unassessed (0% placeholder): High Elegance" in out

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
                        "primary_command": "desloppify resolve fixed ...",
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
        assert "Subjective integrity gap: holistic review stale/missing" in out
        assert "Includes 1 holistic stale/missing signal(s)." in out

    def test_subjective_threshold_uses_configured_target(self, monkeypatch, capsys):
        _patch_common(
            monkeypatch,
            state={
                "findings": {},
                "dimension_scores": {
                    "Naming Quality": {
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
                        "primary_command": "desloppify resolve fixed ...",
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
        assert "Subjective quality (<97%): Naming Quality 96.0%" in out

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
                    "Naming Quality": {
                        "score": 0.0,
                        "strict": 0.0,
                        "issues": 0,
                        "detectors": {"subjective_assessment": {}},
                    },
                    "Logic Clarity": {
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
                        "primary_command": "desloppify resolve fixed ...",
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
        assert "review --prepare --refresh --dimensions" in out
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
                        "summary": "Subjective dimension below target: Naming Quality (94.0%)",
                        "detail": {"dimension_name": "Naming Quality"},
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
            "Naming Quality": {
                "score": 94.0,
                "strict": 94.0,
                "tier": 4,
                "issues": 2,
                "detectors": {"subjective_assessment": {}},
            },
            "Logic Clarity": {
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
        low = _low_subjective_dimensions(dim_scores, threshold=95.0)
        assert low == [
            ("Custom Subjective", 91.0, 1),
            ("Naming Quality", 94.0, 2),
        ]
