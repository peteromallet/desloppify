"""Tests for non-fatal warning handling in review batch helpers."""

from __future__ import annotations

from desloppify.app.commands.review import batches as batches_mod


def test_scored_dimensions_for_lang_records_nonfatal_warning(monkeypatch) -> None:
    def _raise(_lang_name: str):
        raise RuntimeError("unable to load test dimensions payload")

    monkeypatch.setattr(batches_mod, "load_dimensions_for_lang", _raise)
    warnings = []
    assert batches_mod._scored_dimensions_for_lang("python", warning_sink=warnings) == []
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.operation == "review.batches.load_dimensions_for_lang"
    assert warning.target == "python"
    assert warning.error_type == "RuntimeError"
