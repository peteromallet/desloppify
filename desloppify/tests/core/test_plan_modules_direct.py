"""Direct tests for plan helper modules."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import desloppify.engine.planning.common as plan_common_mod
import desloppify.engine.planning.scan as plan_scan_mod
import desloppify.engine.planning.select as plan_select_mod
import desloppify.engine._state.filtering as filtering_mod


class _Phase:
    def __init__(
        self, label: str, slow: bool, findings: list[dict], potentials: dict[str, int]
    ):
        self.label = label
        self.slow = slow
        self._findings = findings
        self._potentials = potentials
        self.run = self._run

    def _run(self, _path, _lang):
        return self._findings, self._potentials


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
    findings, potentials = plan_scan_mod._run_phases(Path("."), lang, full)
    assert [finding["id"] for finding in findings] == ["f1", "s1", "r1"]
    assert potentials == {"fast": 1, "slow": 2, "review": 3}


def test_resolve_lang_prefers_explicit_and_fallbacks(monkeypatch):
    explicit = object()
    assert plan_scan_mod._resolve_lang(explicit, Path(".")) is explicit

    monkeypatch.setattr(plan_scan_mod, "auto_detect_lang", lambda _root: None)
    monkeypatch.setattr(plan_scan_mod, "available_langs", lambda: ["python", "typescript"])
    monkeypatch.setattr(plan_scan_mod, "get_lang", lambda name: f"cfg:{name}")
    resolved = plan_scan_mod._resolve_lang(None, Path("."))
    assert resolved == "cfg:python"


def test_get_next_items_orders_by_tier_confidence_and_count():
    finding_a = filtering_mod.make_finding(
        "smells", "pkg/a.py", "a", tier=3, confidence="low", summary="a"
    )
    finding_a["detail"] = {"count": 2}
    finding_b = filtering_mod.make_finding(
        "smells", "pkg/b.py", "b", tier=2, confidence="medium", summary="b"
    )
    finding_b["detail"] = {"count": 1}
    finding_c = filtering_mod.make_finding(
        "smells", "other/c.py", "c", tier=2, confidence="high", summary="c"
    )
    finding_c["detail"] = {"count": 10}

    state = {"findings": {f["id"]: f for f in [finding_a, finding_b, finding_c]}}

    scoped = plan_select_mod.get_next_items(state, count=2, scan_path="pkg")
    assert len(scoped) == 2
    assert scoped[0]["id"] == finding_b["id"]
    assert scoped[1]["id"] == finding_a["id"]

    top = plan_select_mod.get_next_item(state, tier=2)
    assert top is not None
    assert top["id"] == finding_c["id"]
