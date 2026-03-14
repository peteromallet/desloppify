"""Next.js-specific scanners.

These scanners are intentionally lightweight (regex/heuristic-based) so they
can run as part of the normal smell phase without requiring a full TS AST.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from desloppify.base.discovery.paths import get_project_root
from desloppify.base.discovery.source import find_js_ts_and_tsx_files
from desloppify.languages._framework.node.js_text import (
    code_text as _code_text,
    strip_js_ts_comments as _strip_ts_comments,
)

from .info import NextjsFrameworkInfo

logger = logging.getLogger(__name__)

_USE_CLIENT_RE = re.compile(
    r"""^(?:'use client'|"use client")\s*;?\s*(?://.*)?$"""
)
_MODULE_SPECIFIER_RE = re.compile(
    r"""(?:from\s+['"](?P<from>[^'"]+)['"]|require\(\s*['"](?P<require>[^'"]+)['"]\s*\)|import\(\s*['"](?P<import>[^'"]+)['"]\s*\))"""
)
_NEXT_ROUTER_IMPORT_RE = re.compile(
    r"""(?:from\s+['"]next/router['"]|require\(\s*['"]next/router['"]\s*\))"""
)
_NEXT_NAV_IMPORT_RE = re.compile(
    r"""(?:from\s+['"]next/navigation['"]|require\(\s*['"]next/navigation['"]\s*\)|import\(\s*['"]next/navigation['"]\s*\))"""
)
_NEXT_NAV_HOOK_CALL_RE = re.compile(
    r"""\b(?:useRouter|usePathname|useSearchParams|useParams|useSelectedLayoutSegments|useSelectedLayoutSegment)\s*\("""
)
_CLIENT_HOOK_CALL_RE = re.compile(
    r"""\b(?:useState|useEffect|useLayoutEffect|useReducer|useRef|useContext|useTransition|useDeferredValue|useImperativeHandle|useSyncExternalStore|useMemo|useCallback|useId|useInsertionEffect)\s*\("""
)
_REACT_NAMESPACE_HOOK_CALL_RE = re.compile(
    r"""\bReact\.(?:useState|useEffect|useLayoutEffect|useReducer|useRef|useContext|useTransition|useDeferredValue|useImperativeHandle|useSyncExternalStore|useMemo|useCallback|useId|useInsertionEffect)\s*\("""
)

_NEXTJS_SERVER_ONLY_IMPORTS: set[str] = {
    "next/headers",
    "next/server",
    "next/cache",
    "server-only",
}

# Heuristic list (not exhaustive). These are commonly invalid in client bundles.
_NODE_BUILTIN_MODULES: set[str] = {
    "assert",
    "buffer",
    "child_process",
    "cluster",
    "crypto",
    "dgram",
    "dns",
    "events",
    "fs",
    "http",
    "https",
    "module",
    "net",
    "os",
    "path",
    "perf_hooks",
    "process",
    "stream",
    "timers",
    "tls",
    "tty",
    "url",
    "util",
    "vm",
    "worker_threads",
    "zlib",
}

_NEXTJS_SERVER_EXPORT_RE = re.compile(
    r"""\bexport\s+(?:(?:const|let|var)\s+(?P<const_name>metadata|revalidate|dynamic|runtime|fetchCache|preferredRegion|maxDuration|dynamicParams|metadataBase|viewport|experimental_ppr)\b|(?:async\s+)?function\s+(?P<fn_name>generateMetadata|generateStaticParams|generateViewport)\b)"""
)

_NEXTJS_PAGES_ROUTER_API_RE = re.compile(
    r"""\b(?:export\s+(?:async\s+)?function\s+(?P<fn>getServerSideProps|getStaticProps|getStaticPaths|getInitialProps)\b|export\s+const\s+(?P<const>getServerSideProps|getStaticProps|getStaticPaths|getInitialProps)\b|\b(?P<assign>getServerSideProps|getStaticProps|getStaticPaths|getInitialProps)\s*=)"""
)

_PROCESS_ENV_DOT_RE = re.compile(r"""\bprocess\.env\.([A-Z0-9_]+)\b""")
_PROCESS_ENV_BRACKET_RE = re.compile(r"""\bprocess\.env\[\s*['"]([A-Z0-9_]+)['"]\s*\]""")
_CLIENT_ENV_ALLOWLIST: set[str] = {"NODE_ENV"}

_USE_SERVER_LINE_RE = re.compile(r"""^\s*(?:'use server'|"use server")\s*;?\s*(?://.*)?$""")
_DIRECTIVE_LINE_RE = re.compile(r"""^\s*(?:'[^']*'|"[^"]*")\s*;?\s*(?://.*)?$""")
_ASYNC_EXPORT_DEFAULT_RE = re.compile(r"""\bexport\s+default\s+async\s+(?:function\b|\()""")
_BROWSER_GLOBAL_ACCESS_RE = re.compile(
    r"""\b(?P<global>window|document|localStorage|sessionStorage|navigator)\s*(?:\.|\[)"""
)
_INVALID_REACTY_MODULES_IN_ROUTE_CONTEXT: set[str] = {
    "next/link",
    "next/image",
    "next/head",
    "next/script",
}

# NOTE: `redirect()` and `permanentRedirect()` can be called from Client
# Components during the render phase (not event handlers). We intentionally do
# not flag those patterns here.
_NEXT_NAV_SERVER_API_CALL_RE = re.compile(r"""\b(?P<api>notFound)\s*\(""")
_ROUTE_HANDLER_HTTP_EXPORT_RE = re.compile(
    r"""\bexport\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b"""
)
_EXPORT_DEFAULT_RE = re.compile(r"""\bexport\s+default\b""")
_NEXTAPI_TYPES_RE = re.compile(r"""\bNextApi(?:Request|Response)\b""")
_RES_STATUS_RE = re.compile(r"""\bres\.status\s*\(""")
_RUNTIME_EDGE_RE = re.compile(r"""\bexport\s+const\s+runtime\s*=\s*['"]edge['"]""")


def _has_use_server_directive_at_top(content: str) -> bool:
    first = _first_meaningful_line(content.splitlines())
    return bool(first and _USE_SERVER_LINE_RE.match(first))


def _find_use_server_directive_line_anywhere(content: str) -> int | None:
    for idx, line in enumerate(content.splitlines()[:200], start=1):
        if _USE_SERVER_LINE_RE.match(line.strip()):
            return idx
    return None


def _first_meaningful_line(lines: list[str]) -> str | None:
    """Return the first non-empty, non-comment-only line."""
    in_block_comment = False
    for line in lines[:80]:
        s = line.strip()
        if not s:
            continue
        if in_block_comment:
            end = s.find("*/")
            if end == -1:
                continue
            s = s[end + 2 :].strip()
            in_block_comment = False
            if not s:
                continue
        if s.startswith("//"):
            continue
        if s.startswith("/*"):
            end = s.find("*/", 2)
            if end == -1:
                in_block_comment = True
                continue
            s = s[end + 2 :].strip()
            if not s:
                continue
        return s
    return None


def _has_use_client_directive(content: str) -> bool:
    first = _first_meaningful_line(content.splitlines())
    return bool(first and _USE_CLIENT_RE.match(first))


def _find_use_client_directive_anywhere(content: str) -> int | None:
    for idx, line in enumerate(content.splitlines()[:120], start=1):
        if _USE_CLIENT_RE.match(line.strip()):
            return idx
    return None


def _is_under_any_root(filepath: str, roots: tuple[str, ...]) -> bool:
    return any(filepath == root or filepath.startswith(root.rstrip("/") + "/") for root in roots)


def _iter_import_specifiers(search_text: str) -> list[dict]:
    matches: list[dict] = []
    for match in _MODULE_SPECIFIER_RE.finditer(search_text):
        module = match.group("from") or match.group("require") or match.group("import") or ""
        if not module:
            continue
        line_no = search_text[: match.start()].count("\n") + 1
        matches.append({"module": module, "line": line_no})
    return matches


def _is_node_builtin(module: str) -> bool:
    raw = module[5:] if module.startswith("node:") else module
    base = raw.split("/", 1)[0]
    return base in _NODE_BUILTIN_MODULES


def _find_misplaced_module_use_server_directive(content: str) -> int | None:
    """Find module-level 'use server' directives that are not first.

    Intentionally ignores nested inline server actions where `'use server'` is
    inside a function body (valid Next.js pattern).
    """
    search_text = _strip_ts_comments(content)
    first_directive: str | None = None
    in_prologue = True

    for idx, line in enumerate(search_text.splitlines()[:300], start=1):
        if not line.strip():
            continue

        stripped = line.strip()
        is_directive = bool(_DIRECTIVE_LINE_RE.match(stripped))
        is_use_server = bool(_USE_SERVER_LINE_RE.match(stripped))

        if in_prologue:
            if is_directive:
                if first_directive is None:
                    first_directive = stripped
                if is_use_server and first_directive != stripped:
                    return idx
                continue
            in_prologue = False

        # Top-level misplaced directive after code starts.
        if line == line.lstrip() and is_use_server:
            return idx

    return None


def _is_layout_module(filepath: str) -> bool:
    name = Path(filepath).name
    return name in {"layout.tsx", "layout.ts", "layout.jsx", "layout.js"}


def _is_pages_document_module(filepath: str) -> bool:
    name = Path(filepath).name
    return name.startswith("_document.")


def scan_nextjs_error_files_missing_use_client(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find App Router error boundary modules missing a 'use client' directive."""
    if not info.uses_app_router:
        return [], 0

    targets = {
        "error.tsx",
        "error.ts",
        "error.jsx",
        "error.js",
        "global-error.tsx",
        "global-error.ts",
        "global-error.jsx",
        "global-error.js",
    }
    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        if not _is_under_any_root(filepath, info.app_roots):
            continue
        if Path(filepath).name not in targets:
            continue

        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        if _has_use_client_directive(content):
            continue
        if _find_use_client_directive_anywhere(content) is not None:
            continue

        entries.append({"file": filepath, "line": 1, "name": Path(filepath).name})

    return entries, scanned


def scan_nextjs_pages_router_artifacts_in_app_router(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find Pages Router artifact filenames (e.g. _app.tsx) under app/ trees."""
    if not info.uses_app_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        if not _is_under_any_root(filepath, info.app_roots):
            continue

        scanned += 1
        name = Path(filepath).name
        if not (name.startswith("_app.") or name.startswith("_document.") or name.startswith("_error.")):
            continue

        entries.append({"file": filepath, "line": 1, "name": name})

    return entries, scanned


def scan_nextjs_use_server_not_first(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find modules where 'use server' exists but is not the first meaningful line."""
    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        if _has_use_server_directive_at_top(content):
            continue

        line_no = _find_misplaced_module_use_server_directive(content)
        if line_no is None:
            continue

        entries.append({"file": filepath, "line": line_no})

    return entries, scanned


def scan_nextjs_next_head_in_app_router(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find App Router modules importing legacy next/head."""
    if not info.uses_app_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        if not _is_under_any_root(filepath, info.app_roots):
            continue

        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        search_text = _strip_ts_comments(content)
        for imp in _iter_import_specifiers(search_text):
            if imp["module"] == "next/head":
                entries.append({"file": filepath, "line": imp["line"]})
                break

    return entries, scanned


def scan_nextjs_use_client_not_first(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find App Router modules where 'use client' exists but is not the first meaningful line."""
    if not info.uses_app_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        if not _is_under_any_root(filepath, info.app_roots):
            continue

        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        if _has_use_client_directive(content):
            continue

        line_no = _find_use_client_directive_anywhere(content)
        if line_no is None:
            continue

        entries.append({"file": filepath, "line": line_no})

    return entries, scanned


def scan_nextjs_next_document_misuse(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find next/document imports outside Pages Router `_document.*`."""
    entries: list[dict] = []
    scanned = 0

    for filepath in find_js_ts_and_tsx_files(path):
        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        search_text = _strip_ts_comments(content)
        bad_lines: list[int] = []
        for imp in _iter_import_specifiers(search_text):
            if imp["module"] != "next/document":
                continue

            allowed = info.uses_pages_router and _is_under_any_root(filepath, info.pages_roots) and _is_pages_document_module(filepath)
            if not allowed:
                bad_lines.append(imp["line"])

        if bad_lines:
            entries.append({"file": filepath, "line": min(bad_lines)})

    return entries, scanned


def scan_nextjs_server_navigation_apis_in_client(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find 'use client' modules calling server-only next/navigation APIs (notFound)."""
    if not info.uses_app_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        if not _has_use_client_directive(content):
            continue

        search_text = _strip_ts_comments(content)
        if not _NEXT_NAV_IMPORT_RE.search(search_text):
            continue

        code = _code_text(search_text)
        match = _NEXT_NAV_SERVER_API_CALL_RE.search(code)
        if not match:
            continue

        line_no = code[: match.start()].count("\n") + 1
        entries.append({"file": filepath, "line": line_no, "api": match.group("api")})

    return entries, scanned


def scan_nextjs_browser_globals_missing_use_client(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find App Router modules using browser globals without a 'use client' directive."""
    if not info.uses_app_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        if not _is_under_any_root(filepath, info.app_roots):
            continue
        if filepath.endswith("/route.ts") or filepath.endswith("/route.tsx"):
            continue

        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        if _has_use_client_directive(content):
            continue

        code = _code_text(_strip_ts_comments(content))
        match = _BROWSER_GLOBAL_ACCESS_RE.search(code)
        if not match:
            continue

        line_no = code[: match.start()].count("\n") + 1
        entries.append({"file": filepath, "line": line_no, "global": match.group("global")})

    return entries, scanned


def scan_nextjs_client_layouts(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find App Router layout modules that are marked as client components."""
    if not info.uses_app_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        if not _is_under_any_root(filepath, info.app_roots):
            continue
        if not _is_layout_module(filepath):
            continue

        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        if _has_use_client_directive(content):
            entries.append({"file": filepath, "line": 1})

    return entries, scanned


def scan_nextjs_async_client_components(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find 'use client' modules exporting async default components (invalid in Next.js)."""
    if not info.uses_app_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        if not _has_use_client_directive(content):
            continue

        code = _code_text(_strip_ts_comments(content))
        match = _ASYNC_EXPORT_DEFAULT_RE.search(code)
        if not match:
            continue

        line_no = code[: match.start()].count("\n") + 1
        entries.append({"file": filepath, "line": line_no})

    return entries, scanned


def scan_nextjs_use_server_in_client(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find 'use client' modules that include a 'use server' directive."""
    if not info.uses_app_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        if not _has_use_client_directive(content):
            continue

        # Only module-level 'use server' directives are invalid in 'use client' modules.
        # Inline server actions (e.g. inside a function body) are valid and should not be flagged.
        line_no = _find_misplaced_module_use_server_directive(content)
        if line_no is None:
            continue

        entries.append({"file": filepath, "line": line_no})

    return entries, scanned


def scan_nextjs_server_modules_in_pages_router(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find Pages Router modules importing App Router server-only Next.js modules."""
    if not info.uses_pages_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0

    def _is_pages_api_route(fp: str) -> bool:
        for root in info.pages_roots:
            prefix = root.rstrip("/") + "/api/"
            if fp.startswith(prefix) or fp == (root.rstrip("/") + "/api"):
                return True
        return False

    for filepath in find_js_ts_and_tsx_files(path):
        if not _is_under_any_root(filepath, info.pages_roots):
            continue
        if _is_pages_api_route(filepath):
            continue

        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        search_text = _strip_ts_comments(content)
        imports = _iter_import_specifiers(search_text)
        bad = [imp for imp in imports if imp["module"] in _NEXTJS_SERVER_ONLY_IMPORTS]
        if not bad:
            continue

        entries.append(
            {
                "file": filepath,
                "line": bad[0]["line"],
                "imports": bad,
                "modules": sorted({b["module"] for b in bad}),
            }
        )

    return entries, scanned


def scan_nextjs_pages_api_route_handlers(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find Pages Router API routes using App Router route handler patterns (export GET/POST/etc)."""
    if not info.uses_pages_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0

    def _is_pages_api_route(fp: str) -> bool:
        for root in info.pages_roots:
            prefix = root.rstrip("/") + "/api/"
            if fp.startswith(prefix) or fp == (root.rstrip("/") + "/api"):
                return True
        return False

    for filepath in find_js_ts_and_tsx_files(path):
        if not _is_under_any_root(filepath, info.pages_roots):
            continue
        if not _is_pages_api_route(filepath):
            continue

        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        search_text = _strip_ts_comments(content)
        code = _code_text(search_text)
        match = _ROUTE_HANDLER_HTTP_EXPORT_RE.search(code)
        if not match:
            continue

        line_no = code[: match.start()].count("\n") + 1
        entries.append({"file": filepath, "line": line_no, "method": match.group(1)})

    return entries, scanned


def scan_nextjs_app_router_exports_in_pages_router(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find Pages Router modules exporting App Router metadata/config exports."""
    if not info.uses_pages_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        if not _is_under_any_root(filepath, info.pages_roots):
            continue

        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        search_text = _strip_ts_comments(content)
        matches: list[dict] = []
        for m in _NEXTJS_SERVER_EXPORT_RE.finditer(search_text):
            name = m.group("const_name") or m.group("fn_name") or ""
            if not name:
                continue
            line_no = search_text[: m.start()].count("\n") + 1
            matches.append({"name": name, "line": line_no})
        if not matches:
            continue

        entries.append(
            {
                "file": filepath,
                "line": matches[0]["line"],
                "exports": matches,
                "names": sorted({mm["name"] for mm in matches}),
            }
        )

    return entries, scanned


def scan_rsc_missing_use_client(path: Path, info: NextjsFrameworkInfo) -> tuple[list[dict], int]:
    """Find App Router modules that appear to use client-only React hooks without 'use client'."""
    if not info.uses_app_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        if not _is_under_any_root(filepath, info.app_roots):
            continue

        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        if _has_use_client_directive(content):
            continue
        if _find_use_client_directive_anywhere(content) is not None:
            continue

        code = _code_text(content)
        match = _CLIENT_HOOK_CALL_RE.search(code) or _REACT_NAMESPACE_HOOK_CALL_RE.search(code)
        if not match:
            continue

        line_no = code[: match.start()].count("\n") + 1
        hook = match.group(0).split("(")[0].strip()
        entries.append(
            {
                "file": filepath,
                "line": line_no,
                "hook": hook,
            }
        )

    return entries, scanned


def scan_nextjs_navigation_hooks_missing_use_client(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find App Router modules using next/navigation hooks without 'use client'."""
    if not info.uses_app_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        if not _is_under_any_root(filepath, info.app_roots):
            continue

        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        if _has_use_client_directive(content):
            continue
        if _find_use_client_directive_anywhere(content) is not None:
            continue

        code = _code_text(_strip_ts_comments(content))
        match = _NEXT_NAV_HOOK_CALL_RE.search(code)
        if not match:
            continue

        line_no = code[: match.start()].count("\n") + 1
        hook = match.group(0).split("(")[0].strip()
        entries.append({"file": filepath, "line": line_no, "hook": hook})

    return entries, scanned


def scan_nextjs_server_imports_in_client(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find 'use client' modules importing server-only APIs (Next server modules, node built-ins)."""
    if not info.uses_app_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        if not _has_use_client_directive(content):
            continue

        search_text = _strip_ts_comments(content)
        imports = _iter_import_specifiers(search_text)
        bad: list[dict] = []
        for imp in imports:
            module = imp["module"]
            if module in _NEXTJS_SERVER_ONLY_IMPORTS or _is_node_builtin(module):
                bad.append(imp)

        if not bad:
            continue

        entries.append(
            {
                "file": filepath,
                "line": bad[0]["line"],
                "imports": bad,
                "modules": sorted({b["module"] for b in bad}),
            }
        )

    return entries, scanned


def scan_next_router_imports_in_app_router(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find App Router files importing legacy `next/router`."""
    if not info.uses_app_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        if not _is_under_any_root(filepath, info.app_roots):
            continue
        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        search_text = _strip_ts_comments(content)
        match = _NEXT_ROUTER_IMPORT_RE.search(search_text)
        if not match:
            continue

        line_no = search_text[: match.start()].count("\n") + 1
        entries.append({"file": filepath, "line": line_no})

    return entries, scanned


def scan_nextjs_server_exports_in_client(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find 'use client' modules exporting server-only Next.js metadata/config exports."""
    if not info.uses_app_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        if not _has_use_client_directive(content):
            continue

        search_text = _strip_ts_comments(content)
        matches: list[dict] = []
        for m in _NEXTJS_SERVER_EXPORT_RE.finditer(search_text):
            name = m.group("const_name") or m.group("fn_name") or ""
            if not name:
                continue
            line_no = search_text[: m.start()].count("\n") + 1
            matches.append({"name": name, "line": line_no})

        if not matches:
            continue

        entries.append(
            {
                "file": filepath,
                "line": matches[0]["line"],
                "exports": matches,
                "names": sorted({mm["name"] for mm in matches}),
            }
        )

    return entries, scanned


def scan_nextjs_pages_router_apis_in_app_router(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find Pages Router data fetching APIs used under the App Router tree."""
    if not info.uses_app_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        if not _is_under_any_root(filepath, info.app_roots):
            continue

        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        code = _code_text(_strip_ts_comments(content))
        matches: list[dict] = []
        for m in _NEXTJS_PAGES_ROUTER_API_RE.finditer(code):
            name = m.group("fn") or m.group("const") or m.group("assign") or ""
            if not name:
                continue
            line_no = code[: m.start()].count("\n") + 1
            matches.append({"name": name, "line": line_no})

        if not matches:
            continue

        entries.append(
            {
                "file": filepath,
                "line": matches[0]["line"],
                "apis": matches,
                "names": sorted({mm["name"] for mm in matches}),
            }
        )

    return entries, scanned


def scan_nextjs_env_leaks_in_client(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Find 'use client' modules that reference non-NEXT_PUBLIC_* env vars via process.env."""
    if not info.uses_app_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0
    for filepath in find_js_ts_and_tsx_files(path):
        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        if not _has_use_client_directive(content):
            continue

        code = _code_text(_strip_ts_comments(content))
        occurrences: list[tuple[str, int]] = []
        for m in _PROCESS_ENV_DOT_RE.finditer(code):
            name = m.group(1)
            line_no = code[: m.start()].count("\n") + 1
            occurrences.append((name, line_no))
        for m in _PROCESS_ENV_BRACKET_RE.finditer(code):
            name = m.group(1)
            line_no = code[: m.start()].count("\n") + 1
            occurrences.append((name, line_no))

        bad_occurrences = [
            (name, line_no)
            for (name, line_no) in occurrences
            if not name.startswith("NEXT_PUBLIC_") and name not in _CLIENT_ENV_ALLOWLIST
        ]
        if not bad_occurrences:
            continue

        bad_vars = sorted({name for (name, _) in bad_occurrences})
        first_line = min(line_no for (_, line_no) in bad_occurrences)
        entries.append({"file": filepath, "line": first_line, "vars": bad_vars})

    return entries, scanned


def scan_nextjs_route_handlers_and_middleware_misuse(
    path: Path, info: NextjsFrameworkInfo
) -> tuple[list[dict], int]:
    """Special-case checks for `app/**/route.ts(x)` and `middleware.ts`."""
    if not info.uses_app_router:
        return [], 0

    entries: list[dict] = []
    scanned = 0

    def _is_route_handler(fp: str) -> bool:
        if not _is_under_any_root(fp, info.app_roots):
            return False
        return fp.endswith(("/route.ts", "/route.tsx", "/route.js", "/route.jsx")) or fp in {
            "route.ts",
            "route.tsx",
            "route.js",
            "route.jsx",
        }

    def _is_middleware(fp: str) -> bool:
        return fp in {
            "middleware.ts",
            "middleware.tsx",
            "middleware.js",
            "middleware.jsx",
            "src/middleware.ts",
            "src/middleware.tsx",
            "src/middleware.js",
            "src/middleware.jsx",
        }

    for filepath in find_js_ts_and_tsx_files(path):
        if not (_is_route_handler(filepath) or _is_middleware(filepath)):
            continue

        scanned += 1
        try:
            full = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
            content = full.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping unreadable Next.js candidate %s: %s", filepath, exc)
            continue

        search_text = _strip_ts_comments(content)
        code_text = _code_text(search_text)
        findings: list[dict] = []

        if _has_use_client_directive(content):
            findings.append({"kind": "use_client", "line": 1})

        react_import = re.search(
            r"""(?:from\s+['"]react['"]|require\(\s*['"]react['"]\s*\))""",
            search_text,
        )
        if react_import:
            findings.append(
                {
                    "kind": "react_import",
                    "line": search_text[: react_import.start()].count("\n") + 1,
                }
            )

        hook_call = _CLIENT_HOOK_CALL_RE.search(code_text) or _REACT_NAMESPACE_HOOK_CALL_RE.search(code_text)
        if hook_call:
            findings.append(
                {
                    "kind": "react_hook_call",
                    "line": search_text[: hook_call.start()].count("\n") + 1,
                }
            )

        nav_import = _NEXT_NAV_IMPORT_RE.search(search_text)
        if nav_import:
            findings.append(
                {
                    "kind": "next_navigation_import",
                    "line": search_text[: nav_import.start()].count("\n") + 1,
                }
            )

        if _is_route_handler(filepath):
            default_export = _EXPORT_DEFAULT_RE.search(code_text)
            if default_export:
                findings.append(
                    {
                        "kind": "default_export",
                        "line": code_text[: default_export.start()].count("\n") + 1,
                    }
                )

            nextapi = _NEXTAPI_TYPES_RE.search(code_text)
            if nextapi:
                findings.append(
                    {
                        "kind": "next_api_types",
                        "line": code_text[: nextapi.start()].count("\n") + 1,
                    }
                )

            res_status = _RES_STATUS_RE.search(code_text)
            if res_status:
                findings.append(
                    {
                        "kind": "res_status_usage",
                        "line": code_text[: res_status.start()].count("\n") + 1,
                    }
                )

        imports = _iter_import_specifiers(search_text)
        for imp in imports:
            module = imp["module"]
            if module in _INVALID_REACTY_MODULES_IN_ROUTE_CONTEXT:
                findings.append({"kind": f"invalid_import::{module}", "line": imp["line"]})

        if _is_middleware(filepath):
            for imp in imports:
                module = imp["module"]
                if _is_node_builtin(module):
                    findings.append({"kind": f"node_builtin_import::{module}", "line": imp["line"]})
        elif _is_route_handler(filepath):
            runtime_edge = _RUNTIME_EDGE_RE.search(code_text)
            if runtime_edge:
                for imp in imports:
                    module = imp["module"]
                    if _is_node_builtin(module):
                        findings.append(
                            {"kind": f"edge_runtime_node_builtin_import::{module}", "line": imp["line"]}
                        )

        if filepath.endswith(".tsx"):
            jsx_return = re.search(r"""\breturn\s*<""", code_text)
            if jsx_return:
                findings.append(
                    {
                        "kind": "jsx_return",
                        "line": code_text[: jsx_return.start()].count("\n") + 1,
                    }
                )

        if not findings:
            continue

        kind = "route_handler" if _is_route_handler(filepath) else "middleware"
        entries.append(
            {"file": filepath, "line": findings[0]["line"], "kind": kind, "findings": findings}
        )

    return entries, scanned


def scan_mixed_router_layout(info: NextjsFrameworkInfo) -> list[dict]:
    """Project-level check: both App Router and Pages Router present."""
    if not (info.uses_app_router and info.uses_pages_router):
        return []
    return [
        {
            "file": info.package_json_relpath or "package.json",
            "app_roots": list(info.app_roots),
            "pages_roots": list(info.pages_roots),
        }
    ]


__all__ = [
    "scan_nextjs_app_router_exports_in_pages_router",
    "scan_nextjs_async_client_components",
    "scan_nextjs_browser_globals_missing_use_client",
    "scan_nextjs_client_layouts",
    "scan_nextjs_error_files_missing_use_client",
    "scan_mixed_router_layout",
    "scan_next_router_imports_in_app_router",
    "scan_nextjs_env_leaks_in_client",
    "scan_nextjs_navigation_hooks_missing_use_client",
    "scan_nextjs_next_document_misuse",
    "scan_nextjs_next_head_in_app_router",
    "scan_nextjs_pages_router_apis_in_app_router",
    "scan_nextjs_pages_api_route_handlers",
    "scan_nextjs_pages_router_artifacts_in_app_router",
    "scan_nextjs_route_handlers_and_middleware_misuse",
    "scan_nextjs_server_navigation_apis_in_client",
    "scan_nextjs_server_modules_in_pages_router",
    "scan_nextjs_server_exports_in_client",
    "scan_nextjs_server_imports_in_client",
    "scan_nextjs_use_client_not_first",
    "scan_nextjs_use_server_not_first",
    "scan_nextjs_use_server_in_client",
    "scan_rsc_missing_use_client",
]
