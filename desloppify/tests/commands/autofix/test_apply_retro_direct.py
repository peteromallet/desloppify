"""Direct tests for autofix apply_retro helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import desloppify.app.commands.autofix.apply_retro as retro_mod
from desloppify.languages._framework.base.types import FixResult


class _FakeFixer:
    detector = "unused"

    def __init__(self, entries: list[dict], results: list[dict] | FixResult):
        self._entries = entries
        self._results = results

    def detect(self, _path: Path) -> list[dict]:
        return list(self._entries)

    def fix(self, _entries: list[dict], *, dry_run: bool = False):
        assert dry_run is False
        return self._results


def _state_with_issue(issue_id: str) -> dict:
    return {
        "issues": {
            issue_id: {
                "id": issue_id,
                "status": "open",
                "note": None,
            }
        }
    }


def test_warn_uncommitted_changes_prints_git_checkpoint_hint(monkeypatch, capsys) -> None:
    monkeypatch.setattr(retro_mod.shutil, "which", lambda _name: "/usr/bin/git")
    monkeypatch.setattr(
        retro_mod.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(stdout=" M app.py\n"),
    )

    retro_mod._warn_uncommitted_changes()
    out = capsys.readouterr().out
    assert "uncommitted changes" in out.lower()
    assert "pre-fix checkpoint" in out


def test_warn_uncommitted_changes_swallows_git_errors(monkeypatch) -> None:
    def _boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="git", timeout=5)

    monkeypatch.setattr(retro_mod.shutil, "which", lambda _name: "/usr/bin/git")
    monkeypatch.setattr(retro_mod.subprocess, "run", _boom)
    retro_mod._warn_uncommitted_changes()


def test_cascade_unused_import_cleanup_handles_missing_fixer(capsys) -> None:
    retro_mod._cascade_unused_import_cleanup(
        Path("."),
        state={"issues": {}},
        _prev_score=0.0,
        dry_run=False,
        lang=SimpleNamespace(fixers={}),
    )
    out = capsys.readouterr().out
    assert "no unused-imports fixer" in out


def test_cascade_unused_import_cleanup_handles_no_detected_entries(capsys) -> None:
    fixer = _FakeFixer(entries=[], results=[])
    lang = SimpleNamespace(fixers={"unused-imports": fixer})

    retro_mod._cascade_unused_import_cleanup(
        Path("."),
        state={"issues": {}},
        _prev_score=0.0,
        dry_run=False,
        lang=lang,
    )
    out = capsys.readouterr().out
    assert "no orphaned imports found" in out


def test_cascade_unused_import_cleanup_resolves_cascade_issues(monkeypatch, capsys) -> None:
    monkeypatch.setattr(retro_mod, "rel", lambda value: str(value))

    results = FixResult(
        entries=[
            {
                "file": "src/a.ts",
                "removed": ["Foo"],
                "lines_removed": 2,
            }
        ]
    )
    fixer = _FakeFixer(entries=[{"file": "src/a.ts"}], results=results)
    lang = SimpleNamespace(fixers={"unused-imports": fixer})
    state = _state_with_issue("unused::src/a.ts::Foo")

    retro_mod._cascade_unused_import_cleanup(
        Path("."),
        state=state,
        _prev_score=0.0,
        dry_run=False,
        lang=lang,
    )

    issue = state["issues"]["unused::src/a.ts::Foo"]
    assert issue["status"] == "fixed"
    assert "cascade-unused-imports" in str(issue["note"])

    out = capsys.readouterr().out
    assert "Cascade: removed 1 now-orphaned imports" in out
    assert "auto-resolved 1 import issues" in out


def test_print_fix_retro_renders_skip_reason_labels(capsys) -> None:
    retro_mod._print_fix_retro(
        fixer_name="unused-vars",
        detected=6,
        fixed=4,
        resolved=3,
        skip_reasons={"rest_element": 2},
    )
    out = capsys.readouterr().out
    assert "Skip reasons (2 total)" in out
    assert "has ...rest" in out
