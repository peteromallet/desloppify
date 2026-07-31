"""Razor/Blazor view parsing helpers for C# dependency graph building.

Razor views (``.razor``, ``.cshtml``) are not scored as C# source, but they are
the only place many C# symbols are referenced from. Parsing them here mirrors
the TypeScript plugin's handling of ``.svelte``/``.vue``/``.astro``: the markup
contributes graph edges so code that is reachable only from a view is not
reported as orphaned.
"""

from __future__ import annotations

import re
from pathlib import Path

from desloppify.base.discovery.file_paths import resolve_path
from desloppify.base.discovery.source import SourceDiscoveryOptions, find_source_files

RAZOR_EXTENSIONS = (".razor", ".cshtml")

# Ambient using files: their directives apply to every view in the directory
# subtree below them, which is how Razor itself resolves them.
_AMBIENT_IMPORT_NAMES = ("_Imports.razor", "_ViewImports.cshtml")

_RAZOR_USING_RE = re.compile(
    r"(?m)^\s*@using\s+(?:static\s+)?([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*$"
)
_RAZOR_USING_ALIAS_RE = re.compile(
    r"(?m)^\s*@using\s+[A-Za-z_]\w*\s*=\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*$"
)
_RAZOR_NAMESPACE_RE = re.compile(
    r"(?m)^\s*@namespace\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*$"
)
# @inherits/@implements/@model/@attribute carry fully-qualified type names often
# enough to be worth treating as namespace hints.
_RAZOR_TYPE_DIRECTIVE_RE = re.compile(
    r"(?m)^\s*@(?:inherits|implements|model|typeparam)\s+"
    r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)"
)
_RAZOR_PAGE_RE = re.compile(r"(?m)^\s*@page\b")

# Component usage: <Widget />, <Widget>, </Widget>, <Layout.Header />.
# Razor components are PascalCase; plain HTML elements are lowercase.
_COMPONENT_TAG_RE = re.compile(r"</?([A-Z]\w*(?:\.[A-Z]\w*)*)\b")

# Razor comments (@* ... *@) must not contribute directives or component tags.
_RAZOR_COMMENT_RE = re.compile(r"@\*.*?\*@", re.DOTALL)

# Any PascalCase token in a view is a candidate type reference. Views resolve
# types by name, so linking on the name is closer to what Razor actually does
# than linking on the whole namespace a `@using` names.
_IDENTIFIER_RE = re.compile(r"\b([A-Z]\w*)\b")

_TYPE_DECL_RE = re.compile(
    r"(?m)^[ \t]*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
    r"readonly|ref)\s+)*"
    r"(?:class|record|struct|interface|enum)\s+([A-Za-z_]\w*)"
)

# Extension methods are called as `value.Method()`, so the declaring class name
# never appears in the view. They have to be indexed by method name instead.
_EXTENSION_METHOD_RE = re.compile(
    r"(?m)\bstatic\s+[\w<>\[\],\.\?]+\s+(\w+)\s*(?:<[^>(]*>)?\s*\(\s*(?:\[[^\]]*\]\s*)*this\s+"
)

# Member invocations in a view: `@total.ToBadge()`, `@Model.Items.Format()`.
_INVOKED_MEMBER_RE = re.compile(r"\.(\w+)\s*\(")

# MVC and Razor Pages reference other views by string name, never by type:
# <partial name="_Card" />, Html.PartialAsync("_Card"), Layout = "_Layout".
_VIEW_BY_NAME_RE = re.compile(
    r"""(?:<partial\b[^>]*?\bname\s*=\s*["']([^"']+)["']"""
    r"""|\b(?:Partial|PartialAsync|RenderPartial|RenderPartialAsync)\s*\(\s*["']([^"']+)["']"""
    r"""|\bLayout\s*=\s*["']([^"']+)["'])""",
    re.IGNORECASE,
)

# View components resolve by convention: InvokeAsync("Basket") -> BasketViewComponent.
_VIEW_COMPONENT_RE = re.compile(
    r"""\bComponent\.InvokeAsync\s*(?:<\s*(\w+)\s*>\s*)?\(\s*(?:["']([^"']+)["'])?"""
)

# Tag helpers resolve by convention: <price-tag /> -> PriceTagTagHelper.
_CUSTOM_ELEMENT_RE = re.compile(r"</?([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\b")


def find_razor_files(path: Path | str, exclusions: tuple[str, ...] = ()) -> list[str]:
    """Find Razor view files below ``path``."""
    return find_source_files(
        path,
        list(RAZOR_EXTENSIONS),
        SourceDiscoveryOptions(exclusions=exclusions),
    )


def _read(filepath: str) -> str | None:
    """Read view text, returning None on decode/IO errors."""
    try:
        return Path(resolve_path(filepath)).read_text()
    except (OSError, UnicodeDecodeError):
        return None


class RazorView:
    """Parsed facts about one Razor view."""

    __slots__ = (
        "namespace",
        "usings",
        "is_routable",
        "component_refs",
        "identifiers",
        "invoked_members",
        "view_refs",
        "convention_types",
    )

    def __init__(
        self,
        namespace: str | None,
        usings: set[str],
        is_routable: bool,
        component_refs: set[str],
        identifiers: set[str],
        invoked_members: set[str],
        view_refs: set[str],
        convention_types: set[str],
    ) -> None:
        self.namespace = namespace
        self.usings = usings
        self.is_routable = is_routable
        self.component_refs = component_refs
        self.identifiers = identifiers
        self.invoked_members = invoked_members
        self.view_refs = view_refs
        self.convention_types = convention_types


def parse_razor_metadata(filepath: str) -> RazorView:
    """Parse the directives and symbol references of one Razor view."""
    content = _read(filepath)
    if content is None:
        return RazorView(None, set(), False, set(), set(), set(), set(), set())

    body = _RAZOR_COMMENT_RE.sub("", content)

    namespace = None
    ns_match = _RAZOR_NAMESPACE_RE.search(body)
    if ns_match:
        namespace = ns_match.group(1)

    usings: set[str] = set()
    usings.update(_RAZOR_USING_RE.findall(body))
    usings.update(_RAZOR_USING_ALIAS_RE.findall(body))
    # A qualified type in @inherits/@model implies a dependency on its namespace.
    for qualified in _RAZOR_TYPE_DIRECTIVE_RE.findall(body):
        namespace_part = qualified.rsplit(".", 1)[0]
        if namespace_part:
            usings.add(namespace_part)

    is_routable = bool(_RAZOR_PAGE_RE.search(body))
    component_refs = set(_COMPONENT_TAG_RE.findall(body))
    identifiers = set(_IDENTIFIER_RE.findall(body)) | component_refs
    invoked_members = set(_INVOKED_MEMBER_RE.findall(body))

    view_refs = {
        name
        for groups in _VIEW_BY_NAME_RE.findall(body)
        for name in groups
        if name
    }

    # Types reachable only through a naming convention, never named literally.
    convention_types: set[str] = set()
    for generic_arg, quoted_name in _VIEW_COMPONENT_RE.findall(body):
        if generic_arg:
            convention_types.add(generic_arg)
        if quoted_name:
            convention_types.add(f"{quoted_name}ViewComponent")
    for element in _CUSTOM_ELEMENT_RE.findall(body):
        pascal = "".join(part.capitalize() for part in element.split("-"))
        convention_types.add(f"{pascal}TagHelper")

    return RazorView(
        namespace,
        usings,
        is_routable,
        component_refs,
        identifiers,
        invoked_members,
        view_refs,
        convention_types,
    )


def build_type_index(cs_files: list[str]) -> dict[str, set[str]]:
    """Map declared type name to the C# files declaring it.

    Views resolve types by name, so a name index is what the view edges need.
    Partial classes legitimately map one name to several files.
    """
    index: dict[str, set[str]] = {}
    for filepath in cs_files:
        content = _read(filepath)
        if content is None:
            continue
        for type_name in _TYPE_DECL_RE.findall(content):
            index.setdefault(type_name, set()).add(resolve_path(filepath))
    return index


def build_extension_method_index(cs_files: list[str]) -> dict[str, set[str]]:
    """Map extension method name to the C# files declaring it.

    A view calls these as ``value.Method()``, so the declaring class name never
    appears in the markup and the type index alone cannot reach the file.
    """
    index: dict[str, set[str]] = {}
    for filepath in cs_files:
        content = _read(filepath)
        if content is None:
            continue
        for method_name in _EXTENSION_METHOD_RE.findall(content):
            index.setdefault(method_name, set()).add(resolve_path(filepath))
    return index


def collect_ambient_usings(razor_files: list[str]) -> dict[str, set[str]]:
    """Map each directory containing an ambient import file to its usings.

    Razor applies ``_Imports.razor``/``_ViewImports.cshtml`` to every view in the
    directory subtree below it, so these usings are inherited rather than local.
    """
    ambient: dict[str, set[str]] = {}
    for filepath in razor_files:
        resolved = Path(resolve_path(filepath))
        if resolved.name not in _AMBIENT_IMPORT_NAMES:
            continue
        usings = parse_razor_metadata(filepath).usings
        if not usings:
            continue
        directory = str(resolved.parent)
        ambient.setdefault(directory, set()).update(usings)
    return ambient


def inherited_usings(filepath: str, ambient: dict[str, set[str]]) -> set[str]:
    """Resolve the ambient usings that apply to one view, nearest-first upward."""
    if not ambient:
        return set()
    out: set[str] = set()
    current = Path(resolve_path(filepath)).parent
    while True:
        found = ambient.get(str(current))
        if found:
            out.update(found)
        parent = current.parent
        if parent == current:
            break
        current = parent
    return out


def code_behind_for(filepath: str) -> str | None:
    """Return the code-behind path for a view, if one exists on disk.

    ``Widget.razor`` is completed by the partial class in ``Widget.razor.cs``.
    The markup is the only consumer of that file, so without this edge the
    code-behind looks like an orphan.
    """
    resolved = Path(resolve_path(filepath))
    candidate = resolved.with_name(resolved.name + ".cs")
    if candidate.is_file():
        return str(candidate)
    return None


def build_component_index(razor_files: list[str]) -> dict[str, str]:
    """Map component name to defining view path.

    A Blazor component's name is its filename stem, so ``<Widget />`` resolves
    to ``Widget.razor``. Components declared in plain C# are left unresolved
    rather than guessed at.
    """
    index: dict[str, str] = {}
    for filepath in razor_files:
        resolved = Path(resolve_path(filepath))
        if resolved.suffix != ".razor":
            continue
        if resolved.name in _AMBIENT_IMPORT_NAMES:
            continue
        index.setdefault(resolved.stem, str(resolved))
    return index


def build_view_index(razor_files: list[str]) -> dict[str, str]:
    """Map view name to view path, for views referenced by string name.

    MVC and Razor Pages name partials and layouts as strings, sometimes with a
    path or an extension, so both the stem and the bare filename are indexed.
    """
    index: dict[str, str] = {}
    for filepath in razor_files:
        resolved = Path(resolve_path(filepath))
        index.setdefault(resolved.stem, str(resolved))
        index.setdefault(resolved.name, str(resolved))
    return index


def normalize_view_ref(name: str) -> str:
    """Reduce a view reference such as `~/Pages/Shared/_Card.cshtml` to its stem."""
    trimmed = name.strip().replace("\\", "/").rstrip("/")
    if not trimmed:
        return ""
    return Path(trimmed).stem


__all__ = [
    "RAZOR_EXTENSIONS",
    "RazorView",
    "build_component_index",
    "build_extension_method_index",
    "build_type_index",
    "build_view_index",
    "code_behind_for",
    "collect_ambient_usings",
    "find_razor_files",
    "inherited_usings",
    "normalize_view_ref",
    "parse_razor_metadata",
]
