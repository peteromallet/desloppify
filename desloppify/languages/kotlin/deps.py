"""Kotlin dependency graph built from packages and top-level declarations.

Kotlin imports name declarations, not files: one file may declare many
top-level classes, functions and properties, a file need not be named after
what it declares, and code in the same package uses those names without any
import. Resolving ``import a.b.C`` to ``a/b/C.kt`` therefore misses most real
edges, so this builder indexes every scanned file's package and top-level
names first, then links each file to the files declaring the names it uses:

- explicit imports (``import a.b.C``, ``import a.b.C.Nested``, aliases),
- wildcard imports (``import a.b.*``) and the file's own package, matched by
  the identifiers that appear in the file's code.

Classes registered in an ``AndroidManifest.xml`` (activities, the
application, services, receivers, providers) are started by the platform,
so they get the virtual ``__entrypoint__`` importer instead of being
reported as orphans.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from desloppify.base.discovery.source import read_file_text

ENTRYPOINT_IMPORTER = "__entrypoint__"

_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.`]+)", re.MULTILINE)
_IMPORT_RE = re.compile(
    r"^\s*import\s+([\w.`]+?)(\.\*)?(?:\s+as\s+(\w+))?\s*;?\s*$", re.MULTILINE
)
_DECLARATION_RE = re.compile(r"\b(class|interface|object|fun|val|var|typealias)\b")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_]\w*")
_PRIVATE_RE = re.compile(r"\bprivate\b")
# Words that can follow a declaration keyword but are not the declared name.
_DECLARATION_NOISE = frozenset({"class", "interface", "object", "fun", "val", "var"})

_MANIFEST_NAME = "AndroidManifest.xml"
_MANIFEST_SKIP_DIRS = frozenset({"build", ".gradle", ".git", ".idea", "node_modules"})
_MANIFEST_COMPONENT_RE = re.compile(
    r"<(?:application|activity|activity-alias|service|receiver|provider)\b[^>]*?"
    r"\bandroid:name\s*=\s*\"([^\"]+)\"",
    re.DOTALL,
)
_MANIFEST_PACKAGE_RE = re.compile(r"<manifest\b[^>]*?\bpackage\s*=\s*\"([^\"]+)\"", re.DOTALL)
_GRADLE_BUILD_NAMES = frozenset({"build.gradle.kts", "build.gradle"})
_GRADLE_NAMESPACE_RE = re.compile(r"""\bnamespace\s*=?\s*["']([\w.]+)["']""")


def strip_comments_and_strings(text: str) -> str:
    """Blank out comments and string/char literals, keeping line structure.

    String templates (``"${foo.bar}"``, ``"$name"``) keep their expressions,
    since those are real references.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            end = text.find("\n", i)
            i = n if end == -1 else end
            continue
        if c == "/" and nxt == "*":
            depth = 1
            j = i + 2
            while j < n and depth:
                if text.startswith("/*", j):
                    depth += 1
                    j += 2
                elif text.startswith("*/", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            out.append(_keep_newlines(text[i:j]))
            i = j
            continue
        if c == '"':
            i = _skip_string(text, i, out)
            continue
        if c == "'":
            j = i + 1
            while j < n and text[j] != "'" and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            out.append(" ")
            i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _keep_newlines(chunk: str) -> str:
    return "".join("\n" if ch == "\n" else " " for ch in chunk)


def _skip_string(text: str, start: int, out: list[str]) -> int:
    """Copy a string literal as blanks plus its template expressions."""
    n = len(text)
    raw = text.startswith('"""', start)
    quote = '"""' if raw else '"'
    i = start + len(quote)
    out.append(" ")
    while i < n:
        if text.startswith(quote, i):
            return i + len(quote)
        c = text[i]
        if c == "\\" and not raw:
            i += 2
            continue
        if c == "$" and i + 1 < n:
            if text[i + 1] == "{":
                depth = 1
                j = i + 2
                while j < n and depth:
                    if text[j] == "{":
                        depth += 1
                    elif text[j] == "}":
                        depth -= 1
                    j += 1
                out.append(" " + strip_comments_and_strings(text[i + 2 : j - 1]) + " ")
                i = j
                continue
            match = _IDENTIFIER_RE.match(text, i + 1)
            if match:
                out.append(" " + match.group(0) + " ")
                i = match.end()
                continue
        out.append("\n" if c == "\n" else "")
        i += 1
    return n


def _unquote(name: str) -> str:
    return name.replace("`", "")


def _declared_name(rest: str, keyword: str) -> str | None:
    """Return the name declared by a top-level line after its keyword."""
    if keyword in {"class", "interface", "object", "typealias"}:
        for word in _IDENTIFIER_RE.findall(rest):
            if word not in _DECLARATION_NOISE:
                return word
        return None
    # fun / val / var: the name is the last identifier before the parameter
    # list, type or initializer; it follows any type parameters and receiver
    # (``fun <T> List<T>.name(``, ``val Foo.name: Int``).
    head = rest
    if head.lstrip().startswith("<"):
        depth = 0
        for idx, ch in enumerate(head):
            if ch == "<":
                depth += 1
            elif ch == ">":
                depth -= 1
                if depth == 0:
                    head = head[idx + 1 :]
                    break
    cut = len(head)
    for stop in "(:={":
        pos = head.find(stop)
        if pos != -1:
            cut = min(cut, pos)
    words = _IDENTIFIER_RE.findall(head[:cut])
    words = [w for w in words if w not in _DECLARATION_NOISE]
    return words[-1] if words else None


def top_level_names(code: str) -> set[str]:
    """Names other files can use: non-private top-level declarations.

    ``code`` must be comment- and string-free. Private top-level declarations
    are visible only inside their own file, so they never link files.
    """
    names: set[str] = set()
    depth = 0
    for line in code.splitlines():
        if depth == 0:
            match = _DECLARATION_RE.search(line)
            if (
                match
                and not line.lstrip().startswith(("import ", "package "))
                and not _PRIVATE_RE.search(line, 0, match.start())
            ):
                name = _declared_name(line[match.end() :], match.group(1))
                if name:
                    names.add(name)
        depth += line.count("{") + line.count("(") - line.count("}") - line.count(")")
        depth = max(depth, 0)
    return names


class _KotlinFile:
    __slots__ = ("path", "package", "imports", "star_imports", "names", "identifiers")

    def __init__(self, path: str, text: str) -> None:
        code = strip_comments_and_strings(text)
        self.path = path
        package = _PACKAGE_RE.search(code)
        self.package = _unquote(package.group(1)) if package else ""
        self.imports: list[str] = []
        self.star_imports: list[str] = []
        for match in _IMPORT_RE.finditer(code):
            target = _unquote(match.group(1))
            (self.star_imports if match.group(2) else self.imports).append(target)
        body = _IMPORT_RE.sub("", _PACKAGE_RE.sub("", code))
        self.names = top_level_names(body)
        self.identifiers = set(_IDENTIFIER_RE.findall(body))


class _SymbolIndex:
    def __init__(self, files: list[_KotlinFile]) -> None:
        self.by_fqn: dict[str, set[str]] = defaultdict(set)
        self.by_package: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for kf in files:
            for name in kf.names:
                fqn = f"{kf.package}.{name}" if kf.package else name
                self.by_fqn[fqn].add(kf.path)
                self.by_package[kf.package][name].add(kf.path)

    def resolve(self, qualified: str) -> set[str]:
        """Files declaring ``qualified`` or its closest declared prefix.

        ``a.b.Outer.Inner`` and ``a.b.Enum.ENTRY`` resolve to the file
        declaring ``a.b.Outer`` / ``a.b.Enum``.
        """
        parts = qualified.split(".")
        for end in range(len(parts), 0, -1):
            found = self.by_fqn.get(".".join(parts[:end]))
            if found:
                return found
        return set()

    def used_from_package(self, package: str, identifiers: set[str]) -> set[str]:
        names = self.by_package.get(package)
        if not names:
            return set()
        found: set[str] = set()
        for name in identifiers & names.keys():
            found |= names[name]
        return found


def _find_android_files(root: Path) -> tuple[list[Path], list[Path]]:
    """Return (manifests, Gradle build files) under ``root``, skipping outputs."""
    manifests: list[Path] = []
    build_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _MANIFEST_SKIP_DIRS]
        for filename in filenames:
            if filename == _MANIFEST_NAME:
                manifests.append(Path(dirpath) / filename)
            elif filename in _GRADLE_BUILD_NAMES:
                build_files.append(Path(dirpath) / filename)
    return manifests, build_files


def manifest_entrypoints(root: Path, index: _SymbolIndex) -> set[str]:
    """Files declaring classes that an Android manifest registers."""
    manifests, build_files = _find_android_files(root)
    if not manifests:
        return set()
    # Relative component names (".MainActivity") are resolved against the
    # manifest package or, since AGP 7, the Gradle ``namespace``.
    namespaces: set[str] = set()
    for build_file in build_files:
        namespaces.update(_GRADLE_NAMESPACE_RE.findall(read_file_text(str(build_file)) or ""))
    entry_files: set[str] = set()
    for manifest in manifests:
        text = read_file_text(str(manifest)) or ""
        bases = set(namespaces)
        package = _MANIFEST_PACKAGE_RE.search(text)
        if package:
            bases.add(package.group(1))
        for name in _MANIFEST_COMPONENT_RE.findall(text):
            if name.startswith("."):
                candidates = {base + name for base in bases}
            elif "." not in name:
                candidates = {f"{base}.{name}" for base in bases}
            else:
                candidates = {name}
            for candidate in candidates:
                entry_files |= index.by_fqn.get(candidate, set())
    return entry_files


def build_kotlin_dep_graph(path: Path, file_list: list[str]) -> dict[str, dict[str, Any]]:
    """Build ``{file: {imports, importers, import_count, importer_count}}``."""
    graph: dict[str, dict[str, Any]] = {f: {"imports": set(), "importers": set()} for f in file_list}
    files = []
    for filepath in file_list:
        text = read_file_text(filepath)
        if text is not None:
            files.append(_KotlinFile(filepath, text))
    index = _SymbolIndex(files)

    for kf in files:
        targets: set[str] = set()
        for qualified in kf.imports:
            targets |= index.resolve(qualified)
        for package in [kf.package, *kf.star_imports]:
            targets |= index.used_from_package(package, kf.identifiers)
        for star in kf.star_imports:
            # ``import a.b.Object.*`` pulls members of a declared object/class.
            if star in index.by_fqn:
                targets |= index.by_fqn[star]
        targets.discard(kf.path)
        for target in targets:
            if target in graph:
                graph[kf.path]["imports"].add(target)
                graph[target]["importers"].add(kf.path)

    for entry_file in manifest_entrypoints(Path(path), index):
        if entry_file in graph:
            graph[entry_file]["importers"].add(ENTRYPOINT_IMPORTER)

    for data in graph.values():
        data["import_count"] = len(data["imports"])
        data["importer_count"] = len(data["importers"])
    return graph


__all__ = [
    "ENTRYPOINT_IMPORTER",
    "build_kotlin_dep_graph",
    "manifest_entrypoints",
    "strip_comments_and_strings",
    "top_level_names",
]
