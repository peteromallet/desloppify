"""Next.js framework spec (Node ecosystem)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from desloppify.engine._state.filtering import make_issue
from desloppify.languages._framework.base.types import LangRuntimeContract
from desloppify.languages._framework.node.frameworks.nextjs.info import (
    NextjsFrameworkInfo,
    nextjs_info_from_evidence,
)
from desloppify.languages._framework.node.frameworks.nextjs.scanners import (
    scan_mixed_router_layout,
    scan_next_router_imports_in_app_router,
    scan_nextjs_app_router_exports_in_pages_router,
    scan_nextjs_async_client_components,
    scan_nextjs_browser_globals_missing_use_client,
    scan_nextjs_client_layouts,
    scan_nextjs_env_leaks_in_client,
    scan_nextjs_error_files_missing_use_client,
    scan_nextjs_navigation_hooks_missing_use_client,
    scan_nextjs_next_document_misuse,
    scan_nextjs_next_head_in_app_router,
    scan_nextjs_pages_api_route_handlers,
    scan_nextjs_pages_router_apis_in_app_router,
    scan_nextjs_pages_router_artifacts_in_app_router,
    scan_nextjs_route_handlers_and_middleware_misuse,
    scan_nextjs_server_exports_in_client,
    scan_nextjs_server_imports_in_client,
    scan_nextjs_server_modules_in_pages_router,
    scan_nextjs_server_navigation_apis_in_client,
    scan_nextjs_use_client_not_first,
    scan_nextjs_use_server_in_client,
    scan_nextjs_use_server_not_first,
    scan_rsc_missing_use_client,
)
from desloppify.state_io import Issue

from ..types import DetectionConfig, FrameworkSpec, ScannerRule, ToolIntegration

_NEXTJS_INFO_CACHE_PREFIX = "framework.nextjs.info"


def _nextjs_info(scan_root: Path, lang: LangRuntimeContract) -> NextjsFrameworkInfo:
    key = f"{_NEXTJS_INFO_CACHE_PREFIX}:{scan_root.resolve().as_posix()}"
    cache = getattr(lang, "runtime_cache", None)
    if isinstance(cache, dict):
        cached = cache.get(key)
        if isinstance(cached, NextjsFrameworkInfo):
            return cached

    from desloppify.languages._framework.frameworks.detection import (
        detect_ecosystem_frameworks,
    )

    detection = detect_ecosystem_frameworks(scan_root, lang, "node")
    evidence = detection.present.get("nextjs", {})
    info = nextjs_info_from_evidence(
        evidence,
        package_root=detection.package_root,
        package_json_relpath=detection.package_json_relpath,
    )

    if isinstance(cache, dict):
        cache[key] = info
    return info


def _wrap_scan(
    scan_fn: Callable[[Path, NextjsFrameworkInfo], tuple[list[dict[str, Any]], int]],
) -> Callable[[Path, LangRuntimeContract], tuple[list[dict[str, Any]], int]]:
    def scan(scan_root: Path, lang: LangRuntimeContract) -> tuple[list[dict[str, Any]], int]:
        info = _nextjs_info(scan_root, lang)
        return scan_fn(scan_root, info)

    return scan


def _wrap_info_scan(
    scan_fn: Callable[[NextjsFrameworkInfo], list[dict[str, Any]]],
) -> Callable[[Path, LangRuntimeContract], tuple[list[dict[str, Any]], int]]:
    def scan(scan_root: Path, lang: LangRuntimeContract) -> tuple[list[dict[str, Any]], int]:
        info = _nextjs_info(scan_root, lang)
        return list(scan_fn(info)), 0

    return scan


def _make_line_issue(
    detector: str,
    issue_id: str,
    *,
    tier: int,
    confidence: str,
    summary: str,
) -> Callable[[dict[str, Any]], Issue]:
    return lambda entry: make_issue(
        detector,
        entry["file"],
        issue_id,
        tier=tier,
        confidence=confidence,
        summary=summary,
        detail={"line": entry["line"]},
    )


NEXTJS_SCANNERS: tuple[ScannerRule, ...] = (
    ScannerRule(
        id="use_client_not_first",
        scan=_wrap_scan(scan_nextjs_use_client_not_first),
        issue_factory=_make_line_issue(
            "nextjs",
            "use_client_not_first",
            tier=2,
            confidence="high",
            summary="'use client' directive is present but not the first meaningful line (invalid in Next.js).",
        ),
        log_message=lambda count: (
            "       nextjs: "
            f"{count} App Router files contain a non-top-level 'use client' directive"
        ),
    ),
    ScannerRule(
        id="error_file_missing_use_client",
        scan=_wrap_scan(scan_nextjs_error_files_missing_use_client),
        issue_factory=lambda entry: make_issue(
            "nextjs",
            entry["file"],
            f"error_file_missing_use_client::{entry.get('name','error')}",
            tier=2,
            confidence="high",
            summary="App Router error boundary module is missing 'use client' (required for error.js/error.tsx).",
            detail={"line": entry["line"], "name": entry.get("name")},
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} App Router error boundary files missing 'use client'"
        ),
    ),
    ScannerRule(
        id="pages_router_artifact_in_app_router",
        scan=_wrap_scan(scan_nextjs_pages_router_artifacts_in_app_router),
        issue_factory=lambda entry: make_issue(
            "nextjs",
            entry["file"],
            f"pages_router_artifact_in_app_router::{entry.get('name','artifact')}",
            tier=3,
            confidence="high",
            summary=(
                "App Router tree contains Pages Router artifact file "
                f"{entry.get('name')} (likely migration artifact)."
            ),
            detail={"line": entry["line"], "name": entry.get("name")},
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} Pages Router artifact files found under app/"
        ),
    ),
    ScannerRule(
        id="missing_use_client",
        scan=_wrap_scan(scan_rsc_missing_use_client),
        issue_factory=lambda entry: make_issue(
            "nextjs",
            entry["file"],
            f"missing_use_client::{entry['hook']}",
            tier=2,
            confidence="medium",
            summary=f"Missing 'use client' directive: App Router module uses {entry['hook']}()",
            detail={"line": entry["line"], "hook": entry["hook"]},
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} App Router files missing 'use client'"
        ),
    ),
    ScannerRule(
        id="nav_hook_missing_use_client",
        scan=_wrap_scan(scan_nextjs_navigation_hooks_missing_use_client),
        issue_factory=lambda entry: make_issue(
            "nextjs",
            entry["file"],
            f"nav_hook_missing_use_client::{entry['hook']}",
            tier=2,
            confidence="high",
            summary=f"Missing 'use client' directive: App Router module uses {entry['hook']}()",
            detail={"line": entry["line"], "hook": entry["hook"]},
        ),
        log_message=lambda count: (
            "       nextjs: "
            f"{count} App Router files use next/navigation hooks without 'use client'"
        ),
    ),
    ScannerRule(
        id="server_import_in_client",
        scan=_wrap_scan(scan_nextjs_server_imports_in_client),
        issue_factory=lambda entry: make_issue(
            "nextjs",
            entry["file"],
            "server_import_in_client",
            tier=2,
            confidence="high",
            summary=(
                (
                    "Client component imports server-only modules ("
                    + ", ".join(entry.get("modules", [])[:4])
                    + ")."
                )
                if entry.get("modules")
                else "Client component imports server-only modules."
            ),
            detail={
                "line": entry["line"],
                "modules": entry.get("modules", []),
                "imports": entry.get("imports", []),
            },
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} client components import server-only modules"
        ),
    ),
    ScannerRule(
        id="server_export_in_client",
        scan=_wrap_scan(scan_nextjs_server_exports_in_client),
        issue_factory=lambda entry: make_issue(
            "nextjs",
            entry["file"],
            f"server_export_in_client::{entry.get('export','export')}",
            tier=3,
            confidence="high",
            summary=(
                "Client component exports server-only Next.js module exports "
                f"({entry.get('export')})."
            ),
            detail={"line": entry["line"], "export": entry.get("export")},
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} client components export server-only Next.js exports"
        ),
    ),
    ScannerRule(
        id="pages_router_api_in_app_router",
        scan=_wrap_scan(scan_nextjs_pages_router_apis_in_app_router),
        issue_factory=lambda entry: make_issue(
            "nextjs",
            entry["file"],
            f"pages_router_api_in_app_router::{entry.get('api','api')}",
            tier=3,
            confidence="high",
            summary=(
                "App Router module uses Pages Router data-fetching API "
                f"({entry.get('api')})."
            ),
            detail={"line": entry["line"], "api": entry.get("api")},
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} App Router files use Pages Router APIs"
        ),
    ),
    ScannerRule(
        id="next_head_in_app_router",
        scan=_wrap_scan(scan_nextjs_next_head_in_app_router),
        issue_factory=_make_line_issue(
            "nextjs",
            "next_head_in_app_router",
            tier=3,
            confidence="high",
            summary="App Router module imports next/head (unsupported in App Router).",
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} App Router files import next/head"
        ),
    ),
    ScannerRule(
        id="next_document_misuse",
        scan=_wrap_scan(scan_nextjs_next_document_misuse),
        issue_factory=_make_line_issue(
            "nextjs",
            "next_document_misuse",
            tier=3,
            confidence="high",
            summary="next/document import outside valid Pages Router _document.* file.",
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} files import next/document outside _document.*"
        ),
    ),
    ScannerRule(
        id="browser_global_missing_use_client",
        scan=_wrap_scan(scan_nextjs_browser_globals_missing_use_client),
        issue_factory=lambda entry: make_issue(
            "nextjs",
            entry["file"],
            f"browser_global_missing_use_client::{entry.get('global','global')}",
            tier=2,
            confidence="medium",
            summary=(
                "App Router module accesses browser globals "
                f"({entry.get('global')}) but is missing 'use client'."
            ),
            detail={"line": entry["line"], "global": entry.get("global")},
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} App Router files access browser globals without 'use client'"
        ),
    ),
    ScannerRule(
        id="client_layout_smell",
        scan=_wrap_scan(scan_nextjs_client_layouts),
        issue_factory=_make_line_issue(
            "nextjs",
            "client_layout_smell",
            tier=3,
            confidence="low",
            summary="Client layout detected (layout.* marked 'use client') — consider isolating interactivity to leaf components.",
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} client layouts detected"
        ),
    ),
    ScannerRule(
        id="async_client_component",
        scan=_wrap_scan(scan_nextjs_async_client_components),
        issue_factory=_make_line_issue(
            "nextjs",
            "async_client_component",
            tier=3,
            confidence="high",
            summary="Client component is async (invalid in Next.js).",
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} async client components detected"
        ),
    ),
    ScannerRule(
        id="env_leak_in_client",
        scan=_wrap_scan(scan_nextjs_env_leaks_in_client),
        issue_factory=lambda entry: make_issue(
            "nextjs",
            entry["file"],
            f"env_leak_in_client::{entry.get('var','env')}",
            tier=2,
            confidence="high",
            summary=(
                "Client module accesses non-public env var "
                f"process.env.{entry.get('var')} (only NEXT_PUBLIC_* should be used in client)."
            ),
            detail={"line": entry["line"], "var": entry.get("var")},
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} client modules access non-public env vars"
        ),
    ),
    ScannerRule(
        id="pages_api_route_handlers",
        scan=_wrap_scan(scan_nextjs_pages_api_route_handlers),
        issue_factory=lambda entry: make_issue(
            "nextjs",
            entry["file"],
            "pages_api_route_handlers",
            tier=3,
            confidence="high",
            summary=(
                "Pages Router API route exports App Router route-handler HTTP functions "
                f"({', '.join(entry.get('exports', [])[:4])})."
            ),
            detail={"line": entry["line"], "exports": entry.get("exports", [])},
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} Pages Router API routes export App Router handlers"
        ),
    ),
    ScannerRule(
        id="middleware_misuse",
        scan=_wrap_scan(scan_nextjs_route_handlers_and_middleware_misuse),
        issue_factory=lambda entry: make_issue(
            "nextjs",
            entry["file"],
            f"middleware_misuse::{entry.get('kind','route')}",
            tier=3,
            confidence="medium",
            summary=(
                f"Next.js {entry.get('kind')} misuses route context "
                f"({entry.get('reason')})."
            ),
            detail={
                "line": entry.get("line", 1),
                "kind": entry.get("kind"),
                "reason": entry.get("reason"),
                "findings": entry.get("findings", []),
            },
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} route handler/middleware context misuse findings"
        ),
    ),
    ScannerRule(
        id="server_api_in_client",
        scan=_wrap_scan(scan_nextjs_server_navigation_apis_in_client),
        issue_factory=lambda entry: make_issue(
            "nextjs",
            entry["file"],
            f"server_api_in_client::{entry.get('api','api')}",
            tier=2,
            confidence="high",
            summary=(
                "Client module calls server-only next/navigation API "
                f"({entry.get('api')})."
            ),
            detail={"line": entry["line"], "api": entry.get("api")},
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} client modules call server-only next/navigation APIs"
        ),
    ),
    ScannerRule(
        id="use_server_in_client",
        scan=_wrap_scan(scan_nextjs_use_server_in_client),
        issue_factory=_make_line_issue(
            "nextjs",
            "use_server_in_client",
            tier=2,
            confidence="high",
            summary="'use server' directive in a client module (invalid in Next.js).",
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} client modules contain a module-level 'use server' directive"
        ),
    ),
    ScannerRule(
        id="use_server_not_first",
        scan=_wrap_scan(scan_nextjs_use_server_not_first),
        issue_factory=_make_line_issue(
            "nextjs",
            "use_server_not_first",
            tier=2,
            confidence="high",
            summary="'use server' directive is present but not the first meaningful line (invalid in Next.js).",
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} modules contain a non-top-level 'use server' directive"
        ),
    ),
    ScannerRule(
        id="app_router_exports_in_pages_router",
        scan=_wrap_scan(scan_nextjs_app_router_exports_in_pages_router),
        issue_factory=lambda entry: make_issue(
            "nextjs",
            entry["file"],
            f"app_router_exports_in_pages_router::{entry.get('export','export')}",
            tier=3,
            confidence="high",
            summary=(
                "Pages Router module exports App Router-only module export "
                f"({entry.get('export')})."
            ),
            detail={"line": entry["line"], "export": entry.get("export")},
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} Pages Router files export App Router-only module exports"
        ),
    ),
    ScannerRule(
        id="server_modules_in_pages_router",
        scan=_wrap_scan(scan_nextjs_server_modules_in_pages_router),
        issue_factory=lambda entry: make_issue(
            "nextjs",
            entry["file"],
            "server_modules_in_pages_router",
            tier=3,
            confidence="high",
            summary=(
                (
                    "Pages Router module imports App Router server-only modules ("
                    + ", ".join(entry.get("modules", [])[:4])
                    + ")."
                )
                if entry.get("modules")
                else "Pages Router module imports App Router server-only modules."
            ),
            detail={
                "line": entry["line"],
                "modules": entry.get("modules", []),
                "imports": entry.get("imports", []),
            },
        ),
        log_message=lambda count: (
            "       nextjs: " f"{count} Pages Router files import App Router server-only modules"
        ),
    ),
    ScannerRule(
        id="next_router_in_app_router",
        scan=_wrap_scan(scan_next_router_imports_in_app_router),
        issue_factory=_make_line_issue(
            "nextjs",
            "next_router_in_app_router",
            tier=3,
            confidence="high",
            summary="App Router file imports legacy next/router (prefer next/navigation).",
        ),
        log_message=lambda count: (
            f"       nextjs: {count} App Router files import next/router"
        ),
    ),
    ScannerRule(
        id="mixed_routers",
        scan=_wrap_info_scan(scan_mixed_router_layout),
        issue_factory=lambda entry: make_issue(
            "nextjs",
            entry["file"],
            "mixed_routers",
            tier=4,
            confidence="low",
            summary="Project contains both App Router (app/) and Pages Router (pages/) trees.",
            detail={
                "app_roots": entry.get("app_roots", []),
                "pages_roots": entry.get("pages_roots", []),
            },
        ),
    ),
)


NEXTJS_SPEC = FrameworkSpec(
    id="nextjs",
    label="Next.js",
    ecosystem="node",
    detection=DetectionConfig(
        dependencies=("next",),
        config_files=(
            "next.config.js",
            "next.config.mjs",
            "next.config.cjs",
            "next.config.ts",
        ),
        marker_dirs=("app", "src/app", "pages", "src/pages"),
        script_pattern=r"(?:^|\s)next(?:\s|$)",
        marker_dirs_imply_presence=False,
    ),
    excludes=(),
    scanners=NEXTJS_SCANNERS,
    tools=(
        ToolIntegration(
            id="next_lint",
            label="next lint",
            cmd="npx --no-install next lint --format json",
            fmt="next_lint",
            tier=2,
            slow=True,
            confidence="high",
        ),
    ),
)


__all__ = ["NEXTJS_SPEC"]
