"""Tests for TypeScript Next.js framework detection + scanners."""

from __future__ import annotations

from pathlib import Path

import pytest

import desloppify.languages.typescript.phases_smells as phases_smells_mod
from desloppify.languages.typescript.frameworks import detect_primary_ts_framework
from desloppify.languages.typescript.frameworks.nextjs import nextjs_info_from_detection
from desloppify.languages.typescript.frameworks.nextjs.scanners import (
    scan_nextjs_use_server_not_first,
)


@pytest.fixture(autouse=True)
def _root(tmp_path, set_project_root):
    """Point PROJECT_ROOT at the tmp directory via RuntimeContext."""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def test_detect_nextjs_framework_primary_when_next_and_app_present(tmp_path: Path):
    _write(tmp_path, "package.json", '{"dependencies": {"next": "14.0.0"}}\n')
    _write(tmp_path, "app/page.tsx", "export default function Page() { return <div/> }\n")

    framework = detect_primary_ts_framework(tmp_path)
    info = nextjs_info_from_detection(framework)
    assert info.is_primary is True
    assert info.uses_app_router is True
    assert "app" in info.app_roots


def test_detect_nextjs_framework_not_primary_when_only_app_tree_exists(tmp_path: Path):
    _write(tmp_path, "package.json", '{"dependencies": {"react": "18.3.0"}}\n')
    _write(tmp_path, "app/page.tsx", "export default function Page() { return <div/> }\n")

    framework = detect_primary_ts_framework(tmp_path)
    info = nextjs_info_from_detection(framework)
    assert info.is_primary is False


def test_detect_nextjs_framework_primary_for_external_scan_path(tmp_path: Path):
    external = tmp_path.parent / f"{tmp_path.name}-external-next"
    external.mkdir(parents=True, exist_ok=True)
    (external / "package.json").write_text('{"dependencies": {"next": "14.0.0"}}\n')
    (external / "app").mkdir(parents=True, exist_ok=True)
    (external / "app" / "page.tsx").write_text("export default function Page(){return <div/>}\n")

    framework = detect_primary_ts_framework(external)
    info = nextjs_info_from_detection(framework)
    assert info.is_primary is True
    assert info.package_root == external.resolve()
    assert info.package_json_relpath is not None
    assert info.package_json_relpath.endswith("package.json")


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

    framework = detect_primary_ts_framework(tmp_path)
    info = nextjs_info_from_detection(framework)
    entries, _ = scan_nextjs_use_server_not_first(tmp_path, info)
    files = {entry["file"] for entry in entries}
    assert "app/misplaced.ts" in files
    assert "app/inline-action.tsx" not in files


class _FakeLang:
    zone_map = None

    def __init__(self):
        self.review_cache = {}


def test_phase_smells_adds_nextjs_scanners_when_primary(tmp_path: Path, monkeypatch):
    _write(
        tmp_path,
        "package.json",
        '{"dependencies": {"next": "14.0.0", "react": "18.3.0"}}\n',
    )
    _write(
        tmp_path,
        "app/page.tsx",
        (
            "export default function Page() {\n"
            "  const [x, setX] = useState(0)\n"
            "  return <div>{x}</div>\n"
            "}\n"
        ),
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
    _write(
        tmp_path,
        "app/navhook.tsx",
        "export default function X(){ useRouter(); return null }\n",
    )
    _write(
        tmp_path,
        "app/server-export-in-client.tsx",
        "'use client'\nexport const metadata = {}\nexport default function X(){return null}\n",
    )
    _write(
        tmp_path,
        "app/env-leak.tsx",
        "'use client'\nconsole.log(process.env.SECRET_KEY)\nexport default function X(){return null}\n",
    )
    _write(
        tmp_path,
        "app/pages-api.tsx",
        "export async function getServerSideProps(){ return { props: {} } }\nexport default function X(){return null}\n",
    )
    _write(
        tmp_path,
        "app/api/hello/route.ts",
        (
            "'use client'\n"
            "import { useRouter } from 'next/navigation'\n"
            "export async function GET(){ return new Response('ok') }\n"
        ),
    )
    _write(
        tmp_path,
        "app/api/edge/route.ts",
        (
            "export const runtime = 'edge'\n"
            "import crypto from 'crypto'\n"
            "export async function GET(){ return new Response('ok') }\n"
        ),
    )
    _write(
        tmp_path,
        "app/head-misuse.tsx",
        "import Head from 'next/head'\nexport default function X(){return null}\n",
    )
    _write(
        tmp_path,
        "app/browser-global.tsx",
        "export default function X(){ console.log(window.location.href); return null }\n",
    )
    _write(
        tmp_path,
        "app/layout.tsx",
        "'use client'\nexport default function Layout({children}:{children:any}){return children}\n",
    )
    _write(
        tmp_path,
        "app/async-client.tsx",
        "'use client'\nexport default async function X(){ return null }\n",
    )
    _write(
        tmp_path,
        "app/use-server-in-client.tsx",
        "'use client'\nexport async function action(){ 'use server'; return 1 }\nexport default function X(){return null}\n",
    )
    _write(
        tmp_path,
        "app/late-client.tsx",
        "import x from 'y'\n'use client'\nexport default function X(){ return null }\n",
    )
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
        "app/error.tsx",
        "export default function Error(){ return null }\n",
    )
    _write(
        tmp_path,
        "app/_app.tsx",
        "export default function App(){ return null }\n",
    )
    _write(tmp_path, "pages/index.tsx", "export default function Home(){return null}\n")
    _write(
        tmp_path,
        "pages/bad-next-navigation.tsx",
        "import { useRouter } from 'next/navigation'\nexport default function X(){useRouter(); return null}\n",
    )
    _write(
        tmp_path,
        "pages/meta.tsx",
        "export const metadata = {}\nexport default function X(){return null}\n",
    )
    _write(
        tmp_path,
        "pages/api/hello.ts",
        "export async function GET(){ return new Response('ok') }\n",
    )
    _write(
        tmp_path,
        "pages/bad-server-module.tsx",
        "import { cookies } from 'next/headers'\nexport default function X(){return null}\n",
    )
    _write(
        tmp_path,
        "components/bad-document.tsx",
        "import Document from 'next/document'\nexport default function X(){return null}\n",
    )
    _write(
        tmp_path,
        "middleware.ts",
        "'use client'\nimport React from 'react'\nexport function middleware(){ return null }\n",
    )
    _write(
        tmp_path,
        "server-actions.ts",
        "export const x = 1\n'use server'\nexport async function action(){ return 1 }\n",
    )

    monkeypatch.setattr(phases_smells_mod.smells_detector_mod, "detect_smells", lambda _p: ([], 0))
    monkeypatch.setattr(
        phases_smells_mod.react_state_sync_mod, "detect_state_sync", lambda _p: ([], 0)
    )
    monkeypatch.setattr(
        phases_smells_mod.react_context_mod, "detect_context_nesting", lambda _p: ([], 0)
    )
    monkeypatch.setattr(
        phases_smells_mod.react_hook_bloat_mod,
        "detect_hook_return_bloat",
        lambda _p: ([], 0),
    )
    monkeypatch.setattr(
        phases_smells_mod.react_hook_bloat_mod,
        "detect_boolean_state_explosion",
        lambda _p: ([], 0),
    )

    issues, potentials = phases_smells_mod.phase_smells(tmp_path, _FakeLang())
    detectors = {issue["detector"] for issue in issues}
    assert "nextjs" in detectors

    ids = {issue["id"] for issue in issues}
    assert any("missing_use_client" in issue_id for issue_id in ids)
    assert any("next_router_in_app_router" in issue_id for issue_id in ids)
    assert any("mixed_routers" in issue_id for issue_id in ids)
    assert any("nav_hook_missing_use_client" in issue_id for issue_id in ids)
    assert any("server_import_in_client" in issue_id for issue_id in ids)
    assert any("server_export_in_client" in issue_id for issue_id in ids)
    assert any("env_leak_in_client" in issue_id for issue_id in ids)
    assert any("pages_router_api_in_app_router" in issue_id for issue_id in ids)
    assert any("next_navigation_in_pages_router" in issue_id for issue_id in ids)
    assert any("route_handler_misuse" in issue_id for issue_id in ids)
    assert any("middleware_misuse" in issue_id for issue_id in ids)
    assert any("next_head_in_app_router" in issue_id for issue_id in ids)
    assert any("browser_global_missing_use_client" in issue_id for issue_id in ids)
    assert any("client_layout" in issue_id for issue_id in ids)
    assert any("async_client_component" in issue_id for issue_id in ids)
    assert any("use_server_in_client" in issue_id for issue_id in ids)
    assert any("server_module_in_pages_router" in issue_id for issue_id in ids)
    assert any("next_document_misuse" in issue_id for issue_id in ids)
    assert any("use_client_not_first" in issue_id for issue_id in ids)
    assert any("server_navigation_api_in_client" in issue_id for issue_id in ids)
    assert any("app_router_exports_in_pages_router" in issue_id for issue_id in ids)
    assert any("pages_api_route_handler_exports" in issue_id for issue_id in ids)
    assert any("error_file_missing_use_client" in issue_id for issue_id in ids)
    assert any("pages_router_artifact_in_app_router" in issue_id for issue_id in ids)
    assert any("use_server_not_first" in issue_id for issue_id in ids)

    assert "nextjs" in potentials
    assert potentials["nextjs"] >= 1


def test_phase_smells_skips_nextjs_scanners_when_not_primary(tmp_path: Path, monkeypatch):
    _write(tmp_path, "package.json", '{"dependencies": {"react": "18.3.0"}}\n')
    _write(
        tmp_path,
        "app/page.tsx",
        (
            "export default function Page() {\n"
            "  const [x, setX] = useState(0)\n"
            "  return <div>{x}</div>\n"
            "}\n"
        ),
    )
    _write(
        tmp_path,
        "app/legacy.tsx",
        "import { useRouter } from 'next/router'\nexport default function X(){return null}\n",
    )

    monkeypatch.setattr(phases_smells_mod.smells_detector_mod, "detect_smells", lambda _p: ([], 0))
    monkeypatch.setattr(
        phases_smells_mod.react_state_sync_mod, "detect_state_sync", lambda _p: ([], 0)
    )
    monkeypatch.setattr(
        phases_smells_mod.react_context_mod, "detect_context_nesting", lambda _p: ([], 0)
    )
    monkeypatch.setattr(
        phases_smells_mod.react_hook_bloat_mod,
        "detect_hook_return_bloat",
        lambda _p: ([], 0),
    )
    monkeypatch.setattr(
        phases_smells_mod.react_hook_bloat_mod,
        "detect_boolean_state_explosion",
        lambda _p: ([], 0),
    )

    issues, _ = phases_smells_mod.phase_smells(tmp_path, _FakeLang())
    assert all(issue["detector"] != "nextjs" for issue in issues)


def test_phase_smells_does_not_flag_use_client_with_trailing_comment(tmp_path: Path, monkeypatch):
    _write(
        tmp_path,
        "package.json",
        '{"dependencies": {"next": "14.0.0", "react": "18.3.0"}}\n',
    )
    _write(
        tmp_path,
        "app/page.tsx",
        (
            "\"use client\" // comment after directive\n"
            "export default function Page() {\n"
            "  const [x, setX] = useState(0)\n"
            "  return <div>{x}</div>\n"
            "}\n"
        ),
    )

    monkeypatch.setattr(phases_smells_mod.smells_detector_mod, "detect_smells", lambda _p: ([], 0))
    monkeypatch.setattr(
        phases_smells_mod.react_state_sync_mod, "detect_state_sync", lambda _p: ([], 0)
    )
    monkeypatch.setattr(
        phases_smells_mod.react_context_mod, "detect_context_nesting", lambda _p: ([], 0)
    )
    monkeypatch.setattr(
        phases_smells_mod.react_hook_bloat_mod,
        "detect_hook_return_bloat",
        lambda _p: ([], 0),
    )
    monkeypatch.setattr(
        phases_smells_mod.react_hook_bloat_mod,
        "detect_boolean_state_explosion",
        lambda _p: ([], 0),
    )

    issues, _ = phases_smells_mod.phase_smells(tmp_path, _FakeLang())
    assert all("missing_use_client" not in issue["id"] for issue in issues)
