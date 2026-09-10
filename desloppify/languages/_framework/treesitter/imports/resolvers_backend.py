"""Import resolvers for compiled/backend-oriented languages."""

from __future__ import annotations

import os

from .resolver_cache import discover_jvm_source_roots, read_go_module_path


def resolve_go_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Go imports to local files."""
    del source_file
    if not import_text or "/" not in import_text:
        return None

    go_mod = os.path.join(scan_path, "go.mod")
    module_path = read_go_module_path(go_mod)
    if not module_path or not import_text.startswith(module_path):
        return None

    rel_path = import_text[len(module_path) :].lstrip("/")
    candidate_dir = os.path.join(scan_path, rel_path)
    if os.path.isdir(candidate_dir):
        for filename in sorted(os.listdir(candidate_dir)):
            if filename.endswith(".go") and not filename.endswith("_test.go"):
                return os.path.join(candidate_dir, filename)
    return None


def resolve_rust_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Rust use declarations to local files."""
    del source_file
    if not import_text.startswith("crate::"):
        return None

    parts = import_text[len("crate::") :].split("::")
    if not parts:
        return None

    src_dir = os.path.join(scan_path, "src")
    if not os.path.isdir(src_dir):
        src_dir = scan_path

    path_parts = parts[:-1] if len(parts) > 1 else parts
    candidate = os.path.join(src_dir, *path_parts) + ".rs"
    if os.path.isfile(candidate):
        return candidate

    candidate = os.path.join(src_dir, *path_parts, "mod.rs")
    if os.path.isfile(candidate):
        return candidate

    candidate = os.path.join(src_dir, *parts) + ".rs"
    if os.path.isfile(candidate):
        return candidate
    return None


def _jvm_candidate_roots(scan_path: str) -> list[str]:
    """Source roots to try for JVM package resolution: discovered module
    roots first, then the historical scan-root-relative fallbacks."""
    roots = list(discover_jvm_source_roots(scan_path))
    roots += [
        os.path.join(scan_path, "src", "main", "java"),
        os.path.join(scan_path, "src"),
        os.path.join(scan_path, "app", "src", "main", "java"),
        os.path.join(scan_path, "app", "src", "main", "kotlin"),
        scan_path,
    ]
    return roots


def resolve_java_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Java imports to local files."""
    del source_file
    if import_text.endswith(".*"):
        return None

    parts = import_text.split(".")
    if len(parts) < 2:
        return None

    rel_path = os.path.join(*parts[:-1], parts[-1] + ".java")
    for src_root in _jvm_candidate_roots(scan_path):
        candidate = os.path.join(src_root, rel_path)
        if os.path.isfile(candidate):
            return candidate
    return None


def resolve_kotlin_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Kotlin imports (same structure as Java)."""
    del source_file
    if import_text.endswith(".*"):
        return None

    parts = import_text.split(".")
    if len(parts) < 2:
        return None

    for ext in (".kt", ".kts"):
        rel_path = os.path.join(*parts[:-1], parts[-1] + ext)
        for src_root in _jvm_candidate_roots(scan_path):
            candidate = os.path.join(src_root, rel_path)
            if os.path.isfile(candidate):
                return candidate
    return None


def resolve_cxx_include(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve C/C++ quoted includes to local files."""
    if not import_text:
        return None

    base = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(base, import_text))
    if os.path.isfile(candidate):
        return candidate

    for inc_dir in ["include", "src", "."]:
        candidate = os.path.join(scan_path, inc_dir, import_text)
        if os.path.isfile(candidate):
            return candidate
    return None


def resolve_csharp_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve C# using statements to local files."""
    del source_file
    parts = import_text.split(".")
    if len(parts) < 2:
        return None

    filename = parts[-1] + ".cs"
    for src_root in ["src", ".", "lib"]:
        rel_path = os.path.join(*parts[:-1], filename)
        candidate = os.path.join(scan_path, src_root, rel_path)
        if os.path.isfile(candidate):
            return candidate
        candidate = os.path.join(scan_path, src_root, filename)
        if os.path.isfile(candidate):
            return candidate
    return None


def resolve_dart_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Dart imports to local files."""
    if import_text.startswith("dart:"):
        return None
    if import_text.startswith("package:"):
        parts = import_text[len("package:") :].split("/", 1)
        if len(parts) < 2:
            return None
        candidate = os.path.join(scan_path, "lib", parts[1])
        return candidate if os.path.isfile(candidate) else None

    base = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(base, import_text))
    return candidate if os.path.isfile(candidate) else None


def resolve_scala_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Scala imports to local files."""
    del source_file
    if import_text.endswith("._") or import_text.endswith(".{"):
        return None

    parts = import_text.split(".")
    if len(parts) < 2:
        return None

    rel_path = os.path.join(*parts[:-1], parts[-1] + ".scala")
    for src_root in ["src/main/scala", "src", "."]:
        candidate = os.path.join(scan_path, src_root, rel_path)
        if os.path.isfile(candidate):
            return candidate
    return None


def resolve_swift_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Best-effort local Swift import resolution."""
    text = import_text.strip()
    if not text:
        return None

    module_path = text.replace(".", os.sep)
    leaf = module_path.split(os.sep)[-1]
    source_dir = os.path.dirname(source_file)
    candidates = [
        os.path.join(source_dir, module_path + ".swift"),
        os.path.join(scan_path, module_path + ".swift"),
        os.path.join(scan_path, "Sources", module_path + ".swift"),
        os.path.join(scan_path, "Sources", module_path, f"{leaf}.swift"),
        os.path.join(scan_path, module_path, f"{leaf}.swift"),
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if os.path.isfile(candidate):
            return candidate
    return None
