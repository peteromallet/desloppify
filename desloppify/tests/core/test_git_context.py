"""Unit tests for git-context parsing helpers."""

from __future__ import annotations

from types import SimpleNamespace

import desloppify.base.git_context as git_mod


def test_detect_git_context_success(monkeypatch) -> None:
    results = [
        SimpleNamespace(returncode=0, stdout="abcdef1234567890\n", stderr=""),
        SimpleNamespace(returncode=0, stdout="main\n", stderr=""),
        SimpleNamespace(returncode=0, stdout="/repo\n", stderr=""),
        SimpleNamespace(returncode=0, stdout=" M file.py\n", stderr=""),
    ]
    monkeypatch.setattr(git_mod.shutil, "which", lambda _name: "/usr/bin/git")
    monkeypatch.setattr(git_mod.subprocess, "run", lambda *_a, **_k: results.pop(0))

    ctx = git_mod.detect_git_context()

    assert ctx.available is True
    assert ctx.head_sha == "abcdef123456"
    assert ctx.branch == "main"
    assert ctx.root == "/repo"
    assert ctx.has_uncommitted is True


def test_detect_git_context_returns_unavailable_when_head_fails(monkeypatch) -> None:
    monkeypatch.setattr(git_mod.shutil, "which", lambda _name: "/usr/bin/git")
    monkeypatch.setattr(
        git_mod.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=1, stdout="", stderr="fatal"),
    )

    ctx = git_mod.detect_git_context()
    assert ctx.available is False


def test_update_pr_body_success_and_failure_paths(monkeypatch) -> None:
    monkeypatch.setattr(git_mod.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(
        git_mod.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    assert git_mod.update_pr_body(42, "body") is True

    monkeypatch.setattr(
        git_mod.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=1, stdout="", stderr="denied"),
    )
    assert git_mod.update_pr_body(42, "body") is False

    monkeypatch.setattr(
        git_mod.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("no gh")),
    )
    assert git_mod.update_pr_body(42, "body") is False
