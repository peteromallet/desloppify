"""Direct tests for shared security phase potential accounting."""

from __future__ import annotations

from types import SimpleNamespace

from desloppify.languages._framework.base.shared_phases import phase_security
from desloppify.languages._framework.base.types import LangSecurityResult


def test_security_cache_rejects_results_before_absolute_exclusions():
    from desloppify.languages._framework.base.shared_phases_review import (
        _load_cached_security_result,
        _store_cached_security_result,
    )

    old = {"version": 1, "fingerprint": "same-files", "files_scanned": 2,
           "entries": [{"file": "archive/retired.py"}]}
    assert _load_cached_security_result(old, fingerprint="same-files") is None
    _store_cached_security_result(
        old, fingerprint="same-files",
        result=LangSecurityResult(entries=[], files_scanned=1),
    )
    restored = _load_cached_security_result(old, fingerprint="same-files")
    assert restored is not None and restored.files_scanned == 1 and restored.entries == []


def _lang_stub(*, files_scanned: int):
    return SimpleNamespace(
        zone_map=None,
        name="python",
        file_finder=lambda _path: ["src/app.py"],
        detect_lang_security_detailed=lambda _files, _zone: LangSecurityResult(
            entries=[],
            files_scanned=files_scanned,
        ),
        detector_coverage={},
    )


def test_phase_security_uses_max_scan_count_with_lang_security_result(tmp_path):
    issues, potentials = phase_security(
        tmp_path,
        _lang_stub(files_scanned=7),
        detect_security_issues=lambda _files, _zone, _lang, **_kwargs: ([], 2),
    )
    assert issues == []
    assert potentials == {"security": 7}


def test_phase_security_keeps_cross_lang_scan_count_when_larger(tmp_path):
    issues, potentials = phase_security(
        tmp_path,
        _lang_stub(files_scanned=3),
        detect_security_issues=lambda _files, _zone, _lang, **_kwargs: ([], 9),
    )
    assert issues == []
    assert potentials == {"security": 9}
