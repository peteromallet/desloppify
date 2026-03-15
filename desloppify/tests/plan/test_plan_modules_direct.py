"""Direct tests for plan helper modules."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import desloppify.engine._state.filtering as filtering_mod
from desloppify.engine._work_queue.core import QueueBuildOptions
import desloppify.engine.planning.helpers as plan_common_mod
import desloppify.engine.planning.queue_policy as queue_policy_mod
import desloppify.engine.planning.scan as plan_scan_mod
import desloppify.engine.planning.select as plan_select_mod


class _Phase:
    def __init__(
        self, label: str, slow: bool, issues: list[dict], potentials: dict[str, int]
    ):
        self.label = label
        self.slow = slow
        self._issues = issues
        self._potentials = potentials
        self.run = self._run

    def _run(self, _path, _lang):
        return self._issues, self._potentials


def test_is_subjective_phase_checks_label_and_run_name():
    review_phase = SimpleNamespace(label="Subjective Review", run=lambda *_a: None)
    plain_phase = SimpleNamespace(label="Lint", run=lambda *_a: None)

    def phase_subjective_review(*_args):
        return [], {}

    named_phase = SimpleNamespace(label="Anything", run=phase_subjective_review)

    assert plan_common_mod.is_subjective_phase(review_phase) is True
    assert plan_common_mod.is_subjective_phase(plain_phase) is False
    assert plan_common_mod.is_subjective_phase(named_phase) is True


def test_select_phases_and_run_phases_behavior():
    fast_phase = _Phase("Fast", False, [{"id": "f1"}], {"fast": 1})
    slow_phase = _Phase("Slow", True, [{"id": "s1"}], {"slow": 2})
    review_phase = _Phase("Subjective Review", False, [{"id": "r1"}], {"review": 3})
    lang = SimpleNamespace(
        phases=[fast_phase, slow_phase, review_phase], zone_map=None, name="python"
    )

    objective = plan_scan_mod._select_phases(
        lang, include_slow=True, profile="objective"
    )
    assert [phase.label for phase in objective] == ["Fast", "Slow"]

    ci = plan_scan_mod._select_phases(lang, include_slow=True, profile="ci")
    assert [phase.label for phase in ci] == ["Fast"]

    full = plan_scan_mod._select_phases(lang, include_slow=True, profile="full")
    issues, potentials = plan_scan_mod._run_phases(Path("."), lang, full)
    assert [issue["id"] for issue in issues] == ["f1", "s1", "r1"]
    assert potentials == {"fast": 1, "slow": 2, "review": 3}


def test_generate_issues_from_lang_primes_and_clears_review_prefetch(monkeypatch):
    calls: list[str] = []
    lang = SimpleNamespace(phases=[], zone_map=None, name="python")

    monkeypatch.setattr(plan_scan_mod, "_build_zone_map", lambda *_a, **_k: None)
    monkeypatch.setattr(plan_scan_mod, "_select_phases", lambda *_a, **_k: [])
    monkeypatch.setattr(plan_scan_mod, "_run_phases", lambda *_a, **_k: ([], {}))
    monkeypatch.setattr(plan_scan_mod, "_stamp_issue_context", lambda *_a, **_k: None)
    monkeypatch.setattr(
        plan_scan_mod,
        "prewarm_review_phase_detectors",
        lambda *_a, **_k: calls.append("prime"),
    )
    monkeypatch.setattr(
        plan_scan_mod,
        "clear_review_phase_prefetch",
        lambda *_a, **_k: calls.append("clear"),
    )

    issues, potentials = plan_scan_mod._generate_issues_from_lang(Path("."), lang)

    assert issues == []
    assert potentials == {}
    assert calls == ["prime", "clear"]


def test_generate_issues_from_lang_clears_prefetch_on_phase_error(monkeypatch):
    calls: list[str] = []
    lang = SimpleNamespace(phases=[], zone_map=None, name="python")

    monkeypatch.setattr(plan_scan_mod, "_build_zone_map", lambda *_a, **_k: None)
    monkeypatch.setattr(plan_scan_mod, "_select_phases", lambda *_a, **_k: [])
    monkeypatch.setattr(
        plan_scan_mod,
        "_run_phases",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        plan_scan_mod,
        "prewarm_review_phase_detectors",
        lambda *_a, **_k: calls.append("prime"),
    )
    monkeypatch.setattr(
        plan_scan_mod,
        "clear_review_phase_prefetch",
        lambda *_a, **_k: calls.append("clear"),
    )

    with pytest.raises(RuntimeError, match="boom"):
        plan_scan_mod._generate_issues_from_lang(Path("."), lang)

    assert calls == ["prime", "clear"]


def test_resolve_lang_prefers_explicit_and_fallbacks(monkeypatch):
    explicit = object()
    assert plan_scan_mod._resolve_lang(explicit, Path(".")) is explicit

    monkeypatch.setattr(plan_scan_mod, "auto_detect_lang", lambda _root: None)
    monkeypatch.setattr(plan_scan_mod, "available_langs", lambda: ["python", "typescript"])
    monkeypatch.setattr(plan_scan_mod, "get_lang", lambda name: f"cfg:{name}")
    resolved = plan_scan_mod._resolve_lang(None, Path("."))
    assert resolved == "cfg:python"


def test_get_next_items_orders_by_tier_confidence_and_count():
    issue_a = filtering_mod.make_issue(
        "unused", "pkg/a.py", "a", tier=3, confidence="low", summary="a"
    )
    issue_a["detail"] = {"count": 2}
    issue_b = filtering_mod.make_issue(
        "unused", "pkg/b.py", "b", tier=2, confidence="medium", summary="b"
    )
    issue_b["detail"] = {"count": 1}
    issue_c = filtering_mod.make_issue(
        "unused", "other/c.py", "c", tier=2, confidence="high", summary="c"
    )
    issue_c["detail"] = {"count": 10}

    state = {"issues": {f["id"]: f for f in [issue_a, issue_b, issue_c]}}

    scoped = plan_select_mod.get_next_items(state, count=2, scan_path="pkg")
    assert len(scoped) == 2
    assert scoped[0]["id"] == issue_b["id"]
    assert scoped[1]["id"] == issue_a["id"]

    top = plan_select_mod.get_next_item(state)
    assert top is not None
    assert top["id"] == issue_c["id"]


def test_build_open_plan_queue_uses_core_options_shape(monkeypatch) -> None:
    captured: list[QueueBuildOptions] = []

    def _build_work_queue(_state, *, options):
        captured.append(options)
        return {"items": [], "total": 0, "grouped": {}, "new_ids": set()}

    monkeypatch.setattr(queue_policy_mod, "build_work_queue", _build_work_queue)

    queue_policy_mod.build_open_plan_queue(
        {"config": {"target_strict_score": 91}},
        options=QueueBuildOptions(count=5, scan_path="src"),
    )

    assert captured
    assert isinstance(captured[0], QueueBuildOptions)
    assert captured[0].count == 5
    assert captured[0].scan_path == "src"
    assert captured[0].status == "open"
    assert captured[0].subjective_threshold == 91.0
