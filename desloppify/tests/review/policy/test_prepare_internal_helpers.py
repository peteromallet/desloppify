"""Direct tests for holistic prepare helper internals."""

from __future__ import annotations

from dataclasses import dataclass

from desloppify.intelligence.review._prepare.helpers import (
    HOLISTIC_WORKFLOW,
    append_full_sweep_batch,
)


@dataclass
class _Zone:
    value: str


class _ZoneMap:
    def __init__(self, mapping: dict[str, str]):
        self._mapping = mapping

    def get(self, path: str) -> _Zone:
        return _Zone(self._mapping.get(path, "production"))


def test_holistic_workflow_has_expected_steps():
    assert len(HOLISTIC_WORKFLOW) >= 5
    assert any("review --import" in step for step in HOLISTIC_WORKFLOW)
    assert any("start from listed seed files" in step for step in HOLISTIC_WORKFLOW)
    assert not any("read the listed files" in step for step in HOLISTIC_WORKFLOW)


def test_append_full_sweep_batch_skips_non_production_files():
    lang = type("Lang", (), {"zone_map": _ZoneMap({"tests/test_a.py": "test"})})()
    batches: list[dict] = []
    append_full_sweep_batch(
        batches=batches,
        dims=["logic_clarity"],
        all_files=["src/a.py", "tests/test_a.py"],
        lang=lang,
    )
    assert len(batches) == 1
    assert batches[0]["dimensions"] == ["logic_clarity"]
    assert batches[0]["files_to_read"] == ["src/a.py"]


def test_append_full_sweep_batch_noop_without_dimensions():
    lang = type("Lang", (), {"zone_map": _ZoneMap({})})()
    batches: list[dict] = []
    append_full_sweep_batch(
        batches=batches,
        dims=[],
        all_files=["src/a.py"],
        lang=lang,
    )
    assert batches == []
