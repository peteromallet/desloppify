"""Tests for Next.js framework spec integration (TypeScript)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from desloppify.engine.planning import scan as plan_scan_mod
from desloppify.languages._framework.frameworks.detection import detect_ecosystem_frameworks
from desloppify.languages._framework.node.frameworks.nextjs.info import (
    nextjs_info_from_evidence,
)
from desloppify.languages._framework.node.frameworks.nextjs.scanners import (
    scan_nextjs_server_modules_in_pages_router,
    scan_nextjs_server_navigation_apis_in_client,
    scan_nextjs_use_server_in_client,
    scan_nextjs_use_server_not_first,
)
from desloppify.languages.framework import make_lang_run
from desloppify.languages.typescript import TypeScriptConfig


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


def test_detect_nextjs_present_when_next_dependency_and_app_present(tmp_path: Path):
    _write(tmp_path, "package.json", '{"dependencies": {"next": "14.0.0"}}\n')
    _write(tmp_path, "app/page.tsx", "export default function Page() { return <div/> }\n")

    detection = detect_ecosystem_frameworks(tmp_path, None, "node")
    assert detection.package_root == tmp_path.resolve()
    assert detection.package_json_relpath == "package.json"
    assert "nextjs" in detection.present
    assert "app" in (detection.present["nextjs"].get("marker_dir_hits") or [])


def test_detect_nextjs_absent_when_only_app_tree_exists(tmp_path: Path):
    _write(tmp_path, "package.json", '{"dependencies": {"react": "18.3.0"}}\n')
    _write(tmp_path, "app/page.tsx", "export default function Page() { return <div/> }\n")

    detection = detect_ecosystem_frameworks(tmp_path, None, "node")
    assert "nextjs" not in detection.present


def test_detect_nextjs_package_root_for_external_scan_path(tmp_path: Path):
    external = tmp_path.parent / f"{tmp_path.name}-external-next"
    external.mkdir(parents=True, exist_ok=True)
    (external / "package.json").write_text('{"dependencies": {"next": "14.0.0"}}\n')
    (external / "app").mkdir(parents=True, exist_ok=True)
    (external / "app" / "page.tsx").write_text("export default function Page(){return <div/>}\n")

    detection = detect_ecosystem_frameworks(external, None, "node")
    assert detection.package_root == external.resolve()
    assert detection.package_json_relpath is not None
    assert detection.package_json_relpath.endswith("package.json")
    assert "nextjs" in detection.present


def test_use_server_not_first_ignores_nested_inline_actions(tmp_path: Path):
    _write(tmp_path, "package.json", '{"dependencies": {"next": "14.0.0"}}\n')
    _write(
        tmp_path,
        "app/inline-action.tsx",
        (
            "export default async function Page() {\n"
            "  async function doAction() {\n"
            "    'use server'\n"
            "    return 1\n"
            "  }\n"
            "  return <div>{String(!!doAction)}</div>\n"
            "}\n"
        ),
    )
    _write(
        tmp_path,
        "app/misplaced.ts",
        "export const x = 1\n'use server'\nexport async function action(){ return 1 }\n",
    )

    info = nextjs_info_from_evidence(
        {"marker_dir_hits": ["app"]},
        package_root=tmp_path.resolve(),
        package_json_relpath="package.json",
    )
    entries, _ = scan_nextjs_use_server_not_first(tmp_path, info)
    files = {entry["file"] for entry in entries}
    assert "app/misplaced.ts" in files
    assert "app/inline-action.tsx" not in files


def test_use_server_in_client_ignores_comments_and_string_literals(tmp_path: Path):
    _write(tmp_path, "package.json", '{"dependencies": {"next": "14.0.0"}}\n')
    _write(
        tmp_path,
        "app/page.tsx",
        (
            "'use client'\n"
            'console.log("use server")\n'
            "// 'use server'\n"
            "export default function X(){return null}\n"
        ),
    )

    info = nextjs_info_from_evidence(
        {"marker_dir_hits": ["app"]},
        package_root=tmp_path.resolve(),
        package_json_relpath="package.json",
    )
    entries, _ = scan_nextjs_use_server_in_client(tmp_path, info)
    assert not entries


def test_server_navigation_apis_in_client_only_flags_not_found(tmp_path: Path):
    _write(tmp_path, "package.json", '{"dependencies": {"next": "14.0.0"}}\n')
    _write(
        tmp_path,
        "app/client-redirect.tsx",
        (
            "'use client'\n"
            "import { redirect } from 'next/navigation'\n"
            "export default function X(){ redirect('/'); return null }\n"
        ),
    )
    _write(
        tmp_path,
        "app/client-notfound.tsx",
        (
            "'use client'\n"
            "import { notFound } from 'next/navigation'\n"
            "export default function X(){ notFound(); return null }\n"
        ),
    )

    info = nextjs_info_from_evidence(
        {"marker_dir_hits": ["app"]},
        package_root=tmp_path.resolve(),
        package_json_relpath="package.json",
    )
    entries, _ = scan_nextjs_server_navigation_apis_in_client(tmp_path, info)
    files = {entry["file"] for entry in entries}
    assert "app/client-notfound.tsx" in files
    assert "app/client-redirect.tsx" not in files


def test_server_modules_in_pages_router_skips_pages_api_routes(tmp_path: Path):
    _write(tmp_path, "package.json", '{"dependencies": {"next": "14.0.0"}}\n')
    _write(
        tmp_path,
        "pages/api/edge.ts",
        (
            "import { NextResponse } from 'next/server'\n"
            "export const config = { runtime: 'edge' }\n"
            "export default function handler(){ return NextResponse.json({ ok: true }) }\n"
        ),
    )

    info = nextjs_info_from_evidence(
        {"marker_dir_hits": ["pages"]},
        package_root=tmp_path.resolve(),
        package_json_relpath="package.json",
    )
    entries, _ = scan_nextjs_server_modules_in_pages_router(tmp_path, info)
    assert not entries


def test_typescript_config_includes_nextjs_framework_phases_and_next_lint_is_slow():
    cfg = TypeScriptConfig()
    labels = [getattr(p, "label", "") for p in cfg.phases]
    assert "Next.js framework smells" in labels
    lint = next(p for p in cfg.phases if getattr(p, "label", "") == "next lint")
    assert lint.slow is True


def test_nextjs_smells_phase_emits_issues_when_next_present(tmp_path: Path):
    _write(
        tmp_path,
        "package.json",
        '{"dependencies": {"next": "14.0.0", "react": "18.3.0"}}\n',
    )
    _write(
        tmp_path,
        "app/legacy.tsx",
        "import { useRouter } from 'next/router'\nexport default function X(){return null}\n",
    )
    _write(
        tmp_path,
        "app/server-in-client.tsx",
        (
            "'use client'\n"
            "import { cookies } from 'next/headers'\n"
            "import fs from 'node:fs'\n"
            "export default function X(){return null}\n"
        ),
    )

    cfg = TypeScriptConfig()
    phase = next(p for p in cfg.phases if getattr(p, "label", "") == "Next.js framework smells")
    issues, potentials = phase.run(tmp_path, _FakeLang())
    assert potentials.get("nextjs", 0) >= 1
    assert any(issue.get("detector") == "nextjs" for issue in issues)
    assert any("next_router_in_app_router" in str(issue.get("id", "")) for issue in issues)


def test_next_lint_phase_is_skipped_when_include_slow_false():
    run = make_lang_run(TypeScriptConfig())
    selected = plan_scan_mod._select_phases(run, include_slow=False, profile="full")
    labels = [getattr(p, "label", "") for p in selected]
    assert "Next.js framework smells" in labels
    assert "next lint" not in labels
