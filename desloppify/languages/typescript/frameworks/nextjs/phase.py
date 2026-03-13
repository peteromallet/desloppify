"""Next.js framework smells phase (shared by TS/JS scanning)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from desloppify.engine._state.filtering import make_issue
from desloppify.languages._framework.node.next_lint import run_next_lint
from desloppify.state_io import Issue

from .info import NextjsFrameworkInfo
from .scanners import (
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
    scan_nextjs_next_navigation_in_pages_router,
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


def detect_nextjs_framework_smells(
    scan_root: Path,
    info: NextjsFrameworkInfo,
    log_fn: Callable[[str], None],
) -> tuple[list[Issue], dict[str, int]]:
    results: list[Issue] = []
    nextjs_scanned = 0
    next_lint_potential = 0

    next_lint_entries, next_lint_potential, next_lint_error = run_next_lint(scan_root)
    if next_lint_error:
        results.append(
            make_issue(
                "next_lint",
                info.package_json_relpath or "package.json",
                "unavailable",
                tier=2,
                confidence="high",
                summary=f"Next.js lint did not run: {next_lint_error}.",
                detail={"line": 1, "error": next_lint_error},
            )
        )
        next_lint_potential = max(next_lint_potential, 1)
    else:
        for entry in next_lint_entries:
            results.append(
                make_issue(
                    "next_lint",
                    entry["file"],
                    "lint",
                    tier=2,
                    confidence="high",
                    summary=(
                        f"next lint: {entry['message']} ({entry.get('count', 1)} issue(s) in file)"
                    ),
                    detail={
                        "line": entry.get("line", 1),
                        "count": entry.get("count", 1),
                        "messages": entry.get("messages", []),
                    },
                )
            )
    if next_lint_potential > 0:
        log_fn(f"    next lint: {len(next_lint_entries)} file(s) with issues")

    use_client_not_first_entries, scanned = scan_nextjs_use_client_not_first(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in use_client_not_first_entries:
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                "use_client_not_first",
                tier=2,
                confidence="high",
                summary="'use client' directive is present but not the first meaningful line (invalid in Next.js).",
                detail={"line": entry["line"]},
            )
        )
    if use_client_not_first_entries:
        log_fn(
            "       nextjs: "
            f"{len(use_client_not_first_entries)} App Router files contain a non-top-level 'use client' directive"
        )

    error_missing_client_entries, scanned = scan_nextjs_error_files_missing_use_client(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in error_missing_client_entries:
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                f"error_file_missing_use_client::{entry.get('name','error')}",
                tier=2,
                confidence="high",
                summary="App Router error boundary module is missing 'use client' (required for error.js/error.tsx).",
                detail={"line": entry["line"], "name": entry.get("name")},
            )
        )
    if error_missing_client_entries:
        log_fn(
            "       nextjs: "
            f"{len(error_missing_client_entries)} App Router error boundary files missing 'use client'"
        )

    pages_artifact_entries, scanned = scan_nextjs_pages_router_artifacts_in_app_router(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in pages_artifact_entries:
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                f"pages_router_artifact_in_app_router::{entry.get('name','artifact')}",
                tier=3,
                confidence="high",
                summary=(
                    f"App Router tree contains Pages Router artifact file {entry.get('name')} (likely migration artifact)."
                ),
                detail={"line": entry["line"], "name": entry.get("name")},
            )
        )
    if pages_artifact_entries:
        log_fn("       nextjs: " f"{len(pages_artifact_entries)} Pages Router artifact files found under app/")

    missing_client_entries, scanned = scan_rsc_missing_use_client(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in missing_client_entries:
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                f"missing_use_client::{entry['hook']}",
                tier=2,
                confidence="medium",
                summary=f"Missing 'use client' directive: App Router module uses {entry['hook']}()",
                detail={"line": entry["line"], "hook": entry["hook"]},
            )
        )
    if missing_client_entries:
        log_fn("       nextjs: " f"{len(missing_client_entries)} App Router files missing 'use client'")

    nav_hook_entries, scanned = scan_nextjs_navigation_hooks_missing_use_client(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in nav_hook_entries:
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                f"nav_hook_missing_use_client::{entry['hook']}",
                tier=2,
                confidence="high",
                summary=f"Missing 'use client' directive: App Router module uses {entry['hook']}()",
                detail={"line": entry["line"], "hook": entry["hook"]},
            )
        )
    if nav_hook_entries:
        log_fn(
            "       nextjs: "
            f"{len(nav_hook_entries)} App Router files use next/navigation hooks without 'use client'"
        )

    server_import_entries, scanned = scan_nextjs_server_imports_in_client(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in server_import_entries:
        modules_str = ", ".join(entry.get("modules", [])[:4])
        summary = (
            f"Client component imports server-only modules ({modules_str})."
            if modules_str
            else "Client component imports server-only modules."
        )
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                "server_import_in_client",
                tier=2,
                confidence="high",
                summary=summary,
                detail={
                    "line": entry["line"],
                    "modules": entry.get("modules", []),
                    "imports": entry.get("imports", []),
                },
            )
        )
    if server_import_entries:
        log_fn("       nextjs: " f"{len(server_import_entries)} client components import server-only modules")

    server_export_entries, scanned = scan_nextjs_server_exports_in_client(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in server_export_entries:
        names_str = ", ".join(entry.get("names", [])[:4])
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                "server_export_in_client",
                tier=2,
                confidence="high",
                summary=(
                    f"Client component exports server-only Next.js metadata/config ({names_str})."
                    if names_str
                    else "Client component exports server-only Next.js metadata/config."
                ),
                detail={
                    "line": entry["line"],
                    "names": entry.get("names", []),
                    "exports": entry.get("exports", []),
                },
            )
        )
    if server_export_entries:
        log_fn(
            "       nextjs: "
            f"{len(server_export_entries)} client components export server-only Next.js metadata/config"
        )

    env_leak_entries, scanned = scan_nextjs_env_leaks_in_client(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in env_leak_entries:
        vars_str = ", ".join(entry.get("vars", [])[:4])
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                "env_leak_in_client",
                tier=2,
                confidence="medium",
                summary=(
                    f"Potential env leakage: client component reads {vars_str} via process.env."
                    if vars_str
                    else "Potential env leakage: client component reads non-NEXT_PUBLIC_* vars via process.env."
                ),
                detail={"line": entry["line"], "vars": entry.get("vars", [])},
            )
        )
    if env_leak_entries:
        log_fn("       nextjs: " f"{len(env_leak_entries)} client components reference non-NEXT_PUBLIC_* env vars")

    pages_api_entries, scanned = scan_nextjs_pages_router_apis_in_app_router(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in pages_api_entries:
        names_str = ", ".join(entry.get("names", [])[:4])
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                "pages_router_api_in_app_router",
                tier=3,
                confidence="high",
                summary=(
                    f"App Router file uses Pages Router data fetching API ({names_str})."
                    if names_str
                    else "App Router file uses Pages Router data fetching APIs."
                ),
                detail={
                    "line": entry["line"],
                    "names": entry.get("names", []),
                    "apis": entry.get("apis", []),
                },
            )
        )
    if pages_api_entries:
        log_fn("       nextjs: " f"{len(pages_api_entries)} App Router files reference Pages Router data fetching APIs")

    nav_in_pages_entries, scanned = scan_nextjs_next_navigation_in_pages_router(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in nav_in_pages_entries:
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                "next_navigation_in_pages_router",
                tier=3,
                confidence="medium",
                summary="Pages Router file imports next/navigation (likely misuse / migration artifact).",
                detail={"line": entry["line"]},
            )
        )
    if nav_in_pages_entries:
        log_fn("       nextjs: " f"{len(nav_in_pages_entries)} Pages Router files import next/navigation")

    rh_entries, scanned = scan_nextjs_route_handlers_and_middleware_misuse(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in rh_entries:
        issue_id = "route_handler_misuse" if entry.get("kind") == "route_handler" else "middleware_misuse"
        kind_label = "Route handler" if entry.get("kind") == "route_handler" else "Middleware"
        finding_kinds = ", ".join(f.get("kind", "") for f in entry.get("findings", []) if f.get("kind"))
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                issue_id,
                tier=2,
                confidence="high",
                summary=(
                    f"{kind_label} contains invalid client/React/navigation usage ({finding_kinds})."
                    if finding_kinds
                    else f"{kind_label} contains invalid client/React/navigation usage."
                ),
                detail={"line": entry["line"], "findings": entry.get("findings", [])},
            )
        )
    if rh_entries:
        log_fn("       nextjs: " f"{len(rh_entries)} route handlers/middleware files contain client/React/navigation misuse")

    server_nav_entries, scanned = scan_nextjs_server_navigation_apis_in_client(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in server_nav_entries:
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                f"server_navigation_api_in_client::{entry['api']}",
                tier=2,
                confidence="high",
                summary=f"Client component calls server-only next/navigation API {entry['api']}().",
                detail={"line": entry["line"], "api": entry["api"]},
            )
        )
    if server_nav_entries:
        log_fn("       nextjs: " f"{len(server_nav_entries)} client components call server-only next/navigation APIs")

    app_router_export_in_pages_entries, scanned = scan_nextjs_app_router_exports_in_pages_router(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in app_router_export_in_pages_entries:
        names_str = ", ".join(entry.get("names", [])[:4])
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                "app_router_exports_in_pages_router",
                tier=3,
                confidence="high",
                summary=(
                    f"Pages Router module exports App Router metadata/config ({names_str})."
                    if names_str
                    else "Pages Router module exports App Router metadata/config."
                ),
                detail={
                    "line": entry["line"],
                    "names": entry.get("names", []),
                    "exports": entry.get("exports", []),
                },
            )
        )
    if app_router_export_in_pages_entries:
        log_fn("       nextjs: " f"{len(app_router_export_in_pages_entries)} Pages Router files export App Router metadata/config")

    pages_api_route_handler_entries, scanned = scan_nextjs_pages_api_route_handlers(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in pages_api_route_handler_entries:
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                f"pages_api_route_handler_exports::{entry['method']}",
                tier=3,
                confidence="medium",
                summary=(
                    f"Pages API route exports HTTP method handler {entry['method']}() "
                    "(App Router route handler pattern)."
                ),
                detail={"line": entry["line"], "method": entry["method"]},
            )
        )
    if pages_api_route_handler_entries:
        log_fn("       nextjs: " f"{len(pages_api_route_handler_entries)} Pages API routes export GET/POST/etc handlers")

    next_head_entries, scanned = scan_nextjs_next_head_in_app_router(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in next_head_entries:
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                "next_head_in_app_router",
                tier=3,
                confidence="high",
                summary="App Router module imports legacy next/head (prefer metadata or app/head.tsx).",
                detail={"line": entry["line"]},
            )
        )
    if next_head_entries:
        log_fn(f"       nextjs: {len(next_head_entries)} App Router files import next/head")

    next_doc_entries, scanned = scan_nextjs_next_document_misuse(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in next_doc_entries:
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                "next_document_misuse",
                tier=3,
                confidence="high",
                summary="next/document is used outside pages/_document (likely misuse / migration artifact).",
                detail={"line": entry["line"]},
            )
        )
    if next_doc_entries:
        log_fn(f"       nextjs: {len(next_doc_entries)} files import next/document incorrectly")

    browser_global_entries, scanned = scan_nextjs_browser_globals_missing_use_client(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in browser_global_entries:
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                f"browser_global_missing_use_client::{entry['global']}",
                tier=2,
                confidence="medium",
                summary=f"Missing 'use client' directive: App Router module uses browser global {entry['global']}.",
                detail={"line": entry["line"], "global": entry["global"]},
            )
        )
    if browser_global_entries:
        log_fn("       nextjs: " f"{len(browser_global_entries)} App Router files use browser globals without 'use client'")

    client_layout_entries, scanned = scan_nextjs_client_layouts(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in client_layout_entries:
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                "client_layout",
                tier=3,
                confidence="medium",
                summary="App Router layout is a client component ('use client'); this can force large subtrees client-side.",
                detail={"line": entry["line"]},
            )
        )
    if client_layout_entries:
        log_fn(f"       nextjs: {len(client_layout_entries)} App Router layouts are marked 'use client'")

    async_client_entries, scanned = scan_nextjs_async_client_components(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in async_client_entries:
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                "async_client_component",
                tier=2,
                confidence="high",
                summary="Client component exports an async default component (invalid in Next.js).",
                detail={"line": entry["line"]},
            )
        )
    if async_client_entries:
        log_fn(f"       nextjs: {len(async_client_entries)} client components export async default components")

    use_server_in_client_entries, scanned = scan_nextjs_use_server_in_client(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in use_server_in_client_entries:
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                "use_server_in_client",
                tier=2,
                confidence="high",
                summary="Client module contains a 'use server' directive (invalid combination).",
                detail={"line": entry["line"]},
            )
        )
    if use_server_in_client_entries:
        log_fn(f"       nextjs: {len(use_server_in_client_entries)} client modules contain 'use server'")

    use_server_not_first_entries, scanned = scan_nextjs_use_server_not_first(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in use_server_not_first_entries:
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                "use_server_not_first",
                tier=2,
                confidence="high",
                summary="'use server' directive is present but not the first meaningful line (invalid in Next.js).",
                detail={"line": entry["line"]},
            )
        )
    if use_server_not_first_entries:
        log_fn("       nextjs: " f"{len(use_server_not_first_entries)} files contain a non-top-level 'use server' directive")

    server_mod_in_pages_entries, scanned = scan_nextjs_server_modules_in_pages_router(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in server_mod_in_pages_entries:
        modules_str = ", ".join(entry.get("modules", [])[:4])
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                "server_module_in_pages_router",
                tier=3,
                confidence="high",
                summary=(
                    f"Pages Router module imports App Router server-only module(s): {modules_str}."
                    if modules_str
                    else "Pages Router module imports App Router server-only modules."
                ),
                detail={
                    "line": entry["line"],
                    "modules": entry.get("modules", []),
                    "imports": entry.get("imports", []),
                },
            )
        )
    if server_mod_in_pages_entries:
        log_fn("       nextjs: " f"{len(server_mod_in_pages_entries)} Pages Router files import App Router server-only modules")

    router_entries, scanned = scan_next_router_imports_in_app_router(scan_root, info)
    nextjs_scanned = max(nextjs_scanned, scanned)
    for entry in router_entries:
        results.append(
            make_issue(
                "nextjs",
                entry["file"],
                "next_router_in_app_router",
                tier=3,
                confidence="high",
                summary="App Router file imports legacy next/router (prefer next/navigation).",
                detail={"line": entry["line"]},
            )
        )
    if router_entries:
        log_fn(f"       nextjs: {len(router_entries)} App Router files import next/router")

    for entry in scan_mixed_router_layout(info):
        results.append(
            make_issue(
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
            )
        )

    return results, {"nextjs": nextjs_scanned, "next_lint": next_lint_potential}


__all__ = ["detect_nextjs_framework_smells"]

