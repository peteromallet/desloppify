"""Source-file metadata parsing helpers for C# dependency graph building."""

from __future__ import annotations

import re
from pathlib import Path

from desloppify.base.discovery.file_paths import rel, resolve_path

_USING_RE = re.compile(
    r"(?m)^\s*(?:global\s+)?using\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;"
)
_USING_ALIAS_RE = re.compile(
    r"(?m)^\s*(?:global\s+)?using\s+[A-Za-z_]\w*\s*=\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;"
)
_USING_STATIC_RE = re.compile(
    r"(?m)^\s*(?:global\s+)?using\s+static\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;"
)
_NAMESPACE_RE = re.compile(
    r"(?m)^\s*namespace\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*(?:;|\{)"
)
_NON_CODE_RE = re.compile(
    r'//[^\n]*|/\*[\s\S]*?\*/'
    r'|(?P<raw_quotes>"{3,})[\s\S]*?(?P=raw_quotes)'
    r'|@"(?:""|[^"])*"'
    r'|"(?:\\.|[^"\\])*"'
    r"|'(?:\\.|[^'\\])*'"
)
_TYPE_DECLARATION_RE = re.compile(
    r"\b(?:class|struct|interface|enum|record(?:\s+(?:class|struct))?)\s+"
    r"@?([A-Za-z_]\w*)"
)
_EXTENSION_METHOD_RE = re.compile(
    r"\b([A-Za-z_]\w*)\s*(?:<[^{}();]+>)?\s*\(\s*this\b"
)
_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_]\w*\b")
_MAIN_METHOD_RE = re.compile(r"(?m)\bstatic\s+(?:async\s+)?(?:void|int)\s+Main\s*\(")
_MAUI_APP_FACTORY_RE = re.compile(r"(?m)\bCreateMauiApp\s*\(")
_PLATFORM_BASE_RE = re.compile(
    r"(?m)^\s*(?:public\s+)?(?:partial\s+)?class\s+\w+\s*:\s*"
    r".*\b(?:MauiUIApplicationDelegate|UIApplicationDelegate|UISceneDelegate|MauiWinUIApplication)\b"
)
_PLATFORM_REGISTER_RE = re.compile(r'(?m)\[Register\("AppDelegate"\)\]')

_ENTRY_FILE_HINTS = {
    "Program.cs",
    "Startup.cs",
    "Main.cs",
    "MauiProgram.cs",
    "MainActivity.cs",
    "AppDelegate.cs",
    "SceneDelegate.cs",
    "WinUIApplication.cs",
    "App.xaml.cs",
}
_ENTRY_PATH_HINTS = (
    "/Platforms/Android/",
    "/Platforms/iOS/",
    "/Platforms/MacCatalyst/",
    "/Platforms/Windows/",
)


def is_entrypoint_file(filepath: Path, content: str) -> bool:
    """Best-effort bootstrap detection for app delegates and platform entry files."""
    rel_path = rel(str(filepath)).replace("\\", "/")
    if filepath.name in _ENTRY_FILE_HINTS:
        return True
    is_platform_path = any(hint in rel_path for hint in _ENTRY_PATH_HINTS)
    if is_platform_path and (
        _PLATFORM_BASE_RE.search(content) or _PLATFORM_REGISTER_RE.search(content)
    ):
        return True
    if _MAIN_METHOD_RE.search(content):
        return True
    if _MAUI_APP_FACTORY_RE.search(content):
        return True
    if _PLATFORM_BASE_RE.search(content):
        return True
    if _PLATFORM_REGISTER_RE.search(content):
        return True
    return False


def parse_file_metadata(filepath: str) -> tuple[str | None, set[str], bool]:
    """Return (namespace, using_namespaces, is_entrypoint) for one C# file."""
    abs_path = Path(resolve_path(filepath))
    try:
        content = abs_path.read_text()
    except (OSError, UnicodeDecodeError):
        return None, set(), False

    namespace = None
    ns_match = _NAMESPACE_RE.search(content)
    if ns_match:
        namespace = ns_match.group(1)

    usings: set[str] = set()
    usings.update(_USING_RE.findall(content))
    usings.update(_USING_ALIAS_RE.findall(content))
    usings.update(_USING_STATIC_RE.findall(content))
    return namespace, usings, is_entrypoint_file(abs_path, content)


def parse_file_symbols(filepath: str) -> tuple[set[str], set[str], set[str]]:
    """Return declared types, reference identifiers and extension method names.

    Namespace directives make names available, but do not themselves reference
    types with the same name as a namespace segment. This remains lexical rather
    than full symbol binding.
    """
    try:
        content = Path(resolve_path(filepath)).read_text()
    except (OSError, UnicodeDecodeError):
        return set(), set(), set()
    code = _NON_CODE_RE.sub(" ", content)
    references = _NAMESPACE_RE.sub(" ", code)
    for pattern in (_USING_RE, _USING_ALIAS_RE, _USING_STATIC_RE):
        references = pattern.sub(" ", references)
    return (
        set(_TYPE_DECLARATION_RE.findall(code)),
        set(_IDENTIFIER_RE.findall(references)),
        set(_EXTENSION_METHOD_RE.findall(code)),
    )


def expand_namespace_matches(
    using_ns: str,
    namespace_to_files: dict[str, set[str]],
) -> set[str]:
    """Resolve one using namespace to candidate target files."""
    out: set[str] = set()
    for namespace, files in namespace_to_files.items():
        if (
            namespace == using_ns
            or namespace.startswith(using_ns + ".")
            or using_ns.startswith(namespace + ".")
        ):
            out.update(files)
    return out
