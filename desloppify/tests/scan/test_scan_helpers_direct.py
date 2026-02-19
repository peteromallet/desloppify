"""Direct tests for scan helper utilities."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import desloppify.app.commands.scan.scan_helpers as scan_helpers_mod


def test_profile_and_slow_resolution():
    lang = SimpleNamespace(default_scan_profile="objective")

    assert scan_helpers_mod._resolve_scan_profile(None, lang) == "objective"
    assert scan_helpers_mod._resolve_scan_profile("full", lang) == "full"
    assert scan_helpers_mod._resolve_scan_profile("invalid", lang) == "objective"

    assert scan_helpers_mod._effective_include_slow(True, "full") is True
    assert scan_helpers_mod._effective_include_slow(True, "ci") is False
    assert scan_helpers_mod._effective_include_slow(False, "full") is False


def test_formatting_helpers():
    hidden = scan_helpers_mod._format_hidden_by_detector({"smells": 3, "dupes": 1})
    assert "smells: +3" in hidden
    assert "dupes: +1" in hidden

    delta, color = scan_helpers_mod._format_delta(95.0, 94.0)
    assert delta == " (+1.0)"
    assert color == "green"

    delta, color = scan_helpers_mod._format_delta(94.0, 95.0)
    assert delta == " (-1.0)"
    assert color == "red"


def test_warn_explicit_lang_with_no_files(monkeypatch, capsys, tmp_path):
    args = SimpleNamespace(lang="python")
    lang = SimpleNamespace(name="python")

    import desloppify.languages as lang_mod

    monkeypatch.setattr(lang_mod, "auto_detect_lang", lambda _root: "typescript")

    scan_helpers_mod._warn_explicit_lang_with_no_files(
        args,
        lang,
        Path(tmp_path),
        metrics={"total_files": 0},
    )

    out = capsys.readouterr().out
    assert "No python source files found" in out
    assert "--lang typescript" in out


def test_audit_excluded_dirs_reads_each_file_once(monkeypatch, tmp_path):
    (tmp_path / "used").mkdir()
    (tmp_path / "unused").mkdir()

    call_log: list[str] = []

    def _fake_read(path: str) -> str:
        call_log.append(path)
        if path.endswith("a.py"):
            return "from used import helper"
        return "print('no refs')"

    monkeypatch.setattr(scan_helpers_mod, "read_file_text", _fake_read)

    findings = scan_helpers_mod._audit_excluded_dirs(
        ("used", "unused"),
        ["a.py", "b.py"],
        Path(tmp_path),
    )

    assert len(call_log) == 2
    assert all(str(Path(tmp_path)) in p for p in call_log)
    assert len(findings) == 1
    assert findings[0]["detector"] == "stale_exclude"
    assert findings[0]["file"] == "unused"


def test_audit_excluded_dirs_breaks_when_all_matched(monkeypatch, tmp_path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()

    calls = {"count": 0}

    def _fake_read(_path: str) -> str:
        calls["count"] += 1
        return "alpha beta"

    monkeypatch.setattr(scan_helpers_mod, "read_file_text", _fake_read)

    findings = scan_helpers_mod._audit_excluded_dirs(
        ("alpha", "beta"),
        ["a.py", "b.py", "c.py"],
        Path(tmp_path),
    )

    assert calls["count"] == 1
    assert findings == []
