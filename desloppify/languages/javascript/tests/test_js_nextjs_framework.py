"""Tests for JavaScript Next.js framework smells integration."""

from __future__ import annotations

from pathlib import Path

import pytest

import desloppify.languages.javascript  # noqa: F401 (registration side effect)
from desloppify.languages.framework import get_lang
from desloppify.languages.javascript.phases_nextjs import phase_nextjs


@pytest.fixture(autouse=True)
def _root(tmp_path, set_project_root):
    """Point PROJECT_ROOT at the tmp directory via RuntimeContext."""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


class _FakeLang:
    zone_map = None

    def __init__(self):
        self.review_cache = {}


def test_javascript_plugin_includes_nextjs_phase():
    cfg = get_lang("javascript")
    labels = [getattr(p, "label", "") for p in cfg.phases]
    assert "Next.js framework smells" in labels


def test_phase_nextjs_emits_smells_when_nextjs_is_primary(tmp_path: Path, monkeypatch):
    _write(
        tmp_path,
        "package.json",
        '{"dependencies": {"next": "14.0.0", "react": "18.3.0"}}\n',
    )
    _write(
        tmp_path,
        "app/server-in-client.jsx",
        "'use client'\nimport fs from 'node:fs'\nexport default function X(){return null}\n",
    )

    from desloppify.languages.typescript.frameworks.nextjs import phase as next_phase_mod

    monkeypatch.setattr(next_phase_mod, "run_next_lint", lambda _root: ([], 0, "tests disabled"))

    issues, potentials = phase_nextjs(tmp_path, _FakeLang())
    detectors = {issue["detector"] for issue in issues}
    assert "nextjs" in detectors
    assert "next_lint" in detectors
    assert potentials.get("nextjs", 0) >= 1
    assert potentials.get("next_lint", 0) >= 1

