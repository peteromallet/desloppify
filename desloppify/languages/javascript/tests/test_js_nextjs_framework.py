"""Tests for JavaScript Next.js framework smells integration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import desloppify.languages.javascript  # noqa: F401 (registration side effect)
from desloppify.languages.framework import get_lang


@pytest.fixture(autouse=True)
def _root(tmp_path, set_project_root):
    """Point PROJECT_ROOT at the tmp directory via RuntimeContext."""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


class _FakeLang(SimpleNamespace):
    zone_map = None
    dep_graph = None
    file_finder = None

    def __init__(self):
        super().__init__(review_cache={}, detector_coverage={}, coverage_warnings=[])


def test_javascript_plugin_includes_nextjs_framework_phases_and_next_lint_is_slow():
    cfg = get_lang("javascript")
    labels = [getattr(p, "label", "") for p in cfg.phases]
    assert "Next.js framework smells" in labels
    lint = next(p for p in cfg.phases if getattr(p, "label", "") == "next lint")
    assert lint.slow is True


def test_nextjs_smells_phase_emits_smells_when_next_is_present(tmp_path: Path):
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

    cfg = get_lang("javascript")
    phase = next(p for p in cfg.phases if getattr(p, "label", "") == "Next.js framework smells")
    issues, potentials = phase.run(tmp_path, _FakeLang())
    detectors = {issue.get("detector") for issue in issues}
    assert "nextjs" in detectors
    assert potentials.get("nextjs", 0) >= 1
    assert any("server_import_in_client" in str(issue.get("id", "")) for issue in issues)


def test_nextjs_smells_phase_scans_jsx_error_and_js_middleware(tmp_path: Path):
    _write(
        tmp_path,
        "package.json",
        '{"dependencies": {"next": "14.0.0", "react": "18.3.0"}}\n',
    )
    _write(tmp_path, "app/error.jsx", "export default function Error(){ return null }\n")
    _write(
        tmp_path,
        "middleware.js",
        "'use client'\nimport React from 'react'\nexport function middleware(){ return null }\n",
    )

    cfg = get_lang("javascript")
    phase = next(p for p in cfg.phases if getattr(p, "label", "") == "Next.js framework smells")
    issues, potentials = phase.run(tmp_path, _FakeLang())
    ids = {issue["id"] for issue in issues}
    assert any("error_file_missing_use_client" in issue_id for issue_id in ids)
    assert any("middleware_misuse" in issue_id for issue_id in ids)
    assert potentials.get("nextjs", 0) >= 1
