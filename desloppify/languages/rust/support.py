"""Shared Rust path, manifest, and import-resolution helpers."""

from __future__ import annotations

import functools
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desloppify.base.discovery.file_paths import rel, resolve_path
from desloppify.base.discovery.paths import get_project_root
from desloppify.base.discovery.source import SourceDiscoveryOptions, find_source_files
RUST_FILE_EXCLUSIONS = ["target", ".git", "node_modules", "vendor"]
USE_STATEMENT_RE = re.compile(r"(?m)^\s*(?:pub(?:\([^)]*\))?\s+)?use\s+([^;]+);")
PUB_USE_STATEMENT_RE = re.compile(r"(?m)^\s*pub(?:\([^)]*\))?\s+use\s+([^;]+);")
_MOD_LINE_RE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+([A-Za-z_]\w*)\s*;")
_ATTR_RE = re.compile(r"#\[[^\]]+\]")
_PATH_ATTR_RE = re.compile(r'#\s*\[\s*path\s*=\s*"([^"\n]+)"\s*\]')
_PUBLIC_ITEM_RE = re.compile(r"(?m)^\s*pub\s+(?:struct|enum|trait|type|fn|mod)\s+")
_RUST_LOG_RE = re.compile(r"^\s*(?:println!|eprintln!|dbg!|tracing::)", re.MULTILINE)


@dataclass(frozen=True)
class RustFileContext:
    """Filesystem context required to resolve a Rust source file's module paths."""

    source_file: Path
    manifest_dir: Path
    package_name: str | None
    crate_name: str | None
    source_root: Path
    root_files: tuple[Path, ...]
    module_segments: tuple[str, ...]


@dataclass(frozen=True)
class RustProductionFileIndex:
    """Precomputed lookup tables for production-file resolution."""

    project_root: Path
    by_absolute: dict[str, str]
    by_relative: dict[str, str]


def normalize_crate_name(name: str | None) -> str | None:
    """Normalize Cargo package names to Rust crate names."""
    if not name:
        return None
    text = str(name).strip()
    if not text:
        return None
    return text.replace("-", "_")


def find_rust_files(path: Path | str) -> list[str]:
    """Find Rust source files under path."""
    return find_source_files(
        path,
        [".rs"],
        SourceDiscoveryOptions(exclusions=tuple(RUST_FILE_EXCLUSIONS)),
    )


def build_production_file_index(
    production_files: set[str],
    *,
    project_root: Path | None = None,
) -> RustProductionFileIndex:
    """Build O(1) absolute/relative lookup maps for production files."""
    root = (project_root or get_project_root()).resolve()
    by_absolute: dict[str, str] = {}
    by_relative: dict[str, str] = {}
    for production_file in production_files:
        prod_path = Path(production_file)
        resolved = (
            prod_path.resolve() if prod_path.is_absolute() else (root / prod_path).resolve()
        )
        resolved_str = str(resolved)
        by_absolute.setdefault(resolved_str, production_file)
        try:
            rel_path = rel(resolved, project_root=root)
        except (TypeError, ValueError, OSError):
            rel_path = None
        if rel_path is not None:
            by_relative.setdefault(rel_path, production_file)
    return RustProductionFileIndex(
        project_root=root,
        by_absolute=by_absolute,
        by_relative=by_relative,
    )


def read_text_or_none(path: Path | str, *, errors: str = "replace") -> str | None:
    """Read a file as text, returning ``None`` when the file is unavailable."""
    try:
        return Path(resolve_path(str(path))).read_text(errors=errors)
    except OSError:
        return None


def strip_rust_comments(content: str, *, preserve_lines: bool = False) -> str:
    """Strip Rust line/block comments while preserving literals best-effort."""
    return _strip_rust_comments_impl(content, preserve_lines=preserve_lines)


def _strip_rust_comments_impl(text: str, *, preserve_lines: bool) -> str:
    """Strip Rust comments without treating Markdown backticks as string delimiters."""
    result: list[str] = []
    i = 0
    in_str: str | None = None
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\" and i + 1 < len(text):
                result.append(text[i : i + 2])
                i += 2
                continue
            if ch == in_str:
                in_str = None
            result.append(ch)
            i += 1
            continue

        if ch == '"':
            in_str = ch
            result.append(ch)
            i += 1
            continue

        if ch == "/" and i + 1 < len(text):
            next_char = text[i + 1]
            if next_char == "/":
                if preserve_lines:
                    while i < len(text) and text[i] != "\n":
                        result.append(" ")
                        i += 1
                else:
                    while i < len(text) and text[i] != "\n":
                        i += 1
                continue
            if next_char == "*":
                if preserve_lines:
                    result.extend((" ", " "))
                i += 2
                while i < len(text):
                    if text[i] == "*" and i + 1 < len(text) and text[i + 1] == "/":
                        if preserve_lines:
                            result.extend((" ", " "))
                        i += 2
                        break
                    if preserve_lines:
                        result.append("\n" if text[i] == "\n" else " ")
                    i += 1
                continue

        result.append(ch)
        i += 1
    return "".join(result)


def _strip_c_style_comments_preserve_lines(text: str) -> str:
    """Strip C-style comments while preserving newlines for line-number accuracy."""
    return _strip_rust_comments_impl(text, preserve_lines=True)


def normalize_rust_body(body: str) -> str:
    """Normalize a Rust function body for duplicate detection."""
    stripped = strip_rust_comments(body)
    lines = []
    for raw_line in stripped.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _RUST_LOG_RE.match(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def has_public_api_markers(content: str) -> bool:
    """Return True when a file exposes public API surface."""
    return bool(_PUBLIC_ITEM_RE.search(strip_rust_comments(content)))


def iter_mod_declarations(content: str) -> list[str]:
    """Return `mod foo;` declarations from a file."""
    return [name for name, _ in iter_mod_targets(content)]


def iter_mod_targets(content: str) -> list[tuple[str, str | None]]:
    """Return `mod foo;` declarations plus optional `#[path = ...]` overrides."""
    stripped = strip_rust_comments(content)
    declarations: list[tuple[str, str | None]] = []
    attrs: list[str] = []
    for raw_line in stripped.splitlines():
        line = raw_line.strip()
        if not line:
            attrs = []
            continue

        if line.startswith("#["):
            inline_attrs = _ATTR_RE.findall(line)
            if inline_attrs:
                attrs.extend(inline_attrs)
                line = _ATTR_RE.sub("", line).strip()
                if not line:
                    continue
            else:
                attrs = []
                continue

        match = _MOD_LINE_RE.match(line)
        if match:
            declarations.append((match.group(1), _path_override_from_attrs(attrs)))
        attrs = []
    return declarations


def iter_use_specs(content: str) -> list[str]:
    """Return normalized Rust `use` / `pub use` specs from a file."""
    return _iter_use_specs_with_pattern(content, USE_STATEMENT_RE)


def iter_pub_use_specs(content: str) -> list[str]:
    """Return normalized `pub use` specs from a file."""
    return _iter_use_specs_with_pattern(content, PUB_USE_STATEMENT_RE)


def _iter_use_specs_with_pattern(content: str, pattern: re.Pattern[str]) -> list[str]:
    """Extract `use` specs while ignoring string-literal contents.

    Rust files can contain natural-language strings (for example JSON tool
    descriptions) with lines that begin with "use ...". We mask string literal
    content before regex matching so import extraction only sees real code.
    """
    stripped = strip_rust_comments(content, preserve_lines=True)
    masked = _mask_rust_string_literals_preserve_lines(stripped)
    specs: list[str] = []
    for match in pattern.finditer(masked):
        start, end = match.span(1)
        specs.extend(_expand_use_tree(stripped[start:end]))
    return specs


def _mask_rust_string_literals_preserve_lines(content: str) -> str:
    """Replace string literal contents with spaces while preserving newlines."""
    chars = list(content)
    result = chars[:]
    length = len(chars)
    i = 0
    in_normal_string = False
    raw_hash_count: int | None = None
    while i < length:
        ch = chars[i]

        if raw_hash_count is not None:
            if ch == '"':
                if raw_hash_count == 0:
                    result[i] = " "
                    raw_hash_count = None
                    i += 1
                    continue
                hash_count = raw_hash_count
                hashes = "#" * hash_count
                if content.startswith(hashes, i + 1):
                    result[i] = " "
                    for j in range(i + 1, i + 1 + hash_count):
                        result[j] = " "
                    raw_hash_count = None
                    i += 1 + hash_count
                    continue
            result[i] = "\n" if ch == "\n" else " "
            i += 1
            continue

        if in_normal_string:
            if ch == "\\" and i + 1 < length:
                result[i] = " "
                result[i + 1] = "\n" if chars[i + 1] == "\n" else " "
                i += 2
                continue
            result[i] = "\n" if ch == "\n" else " "
            if ch == '"':
                in_normal_string = False
            i += 1
            continue

        raw_prefix = _raw_string_prefix_length(chars, i)
        if raw_prefix is not None:
            prefix_len, hashes = raw_prefix
            for j in range(i, i + prefix_len):
                result[j] = " "
            raw_hash_count = hashes
            i += prefix_len
            continue

        if ch == '"':
            result[i] = " "
            in_normal_string = True
            i += 1
            continue

        if ch == "b" and i + 1 < length and chars[i + 1] == '"':
            result[i] = " "
            result[i + 1] = " "
            in_normal_string = True
            i += 2
            continue

        i += 1
    return "".join(result)


def _raw_string_prefix_length(chars: list[str], index: int) -> tuple[int, int] | None:
    """Return (prefix_length, hash_count) for raw string prefixes at index."""
    length = len(chars)
    j = index
    if chars[j] == "b":
        j += 1
        if j >= length:
            return None
    if chars[j] != "r":
        return None
    j += 1
    hash_count = 0
    while j < length and chars[j] == "#":
        hash_count += 1
        j += 1
    if j >= length or chars[j] != '"':
        return None
    return (j - index + 1, hash_count)


def find_manifest_dir(path: Path | str) -> Path | None:
    """Walk up from path to the nearest Cargo.toml root."""
    candidate = Path(resolve_path(str(path)))
    if candidate.is_file():
        candidate = candidate.parent
    for current in (candidate, *candidate.parents):
        if (current / "Cargo.toml").is_file():
            return current
    return None


def read_package_name(manifest_dir: Path) -> str | None:
    """Read package name from Cargo.toml, if present."""
    data = _read_manifest_data(manifest_dir)
    package = data.get("package")
    if not isinstance(package, dict):
        return None
    return normalize_crate_name(package.get("name"))


def read_library_crate_name(manifest_dir: Path) -> str | None:
    """Read the library crate name, falling back to the package name."""
    data = _read_manifest_data(manifest_dir)
    lib = data.get("lib")
    if isinstance(lib, dict):
        name = normalize_crate_name(lib.get("name"))
        if name:
            return name
    package = data.get("package")
    if not isinstance(package, dict):
        return None
    return normalize_crate_name(package.get("name"))


def _read_manifest_data(manifest_dir: Path) -> dict[str, Any]:
    """Parse a Cargo manifest into a dictionary."""
    data = _load_toml_dict(manifest_dir / "Cargo.toml")
    return data or {}


def build_workspace_package_index(scan_root: Path | None = None) -> dict[str, Path]:
    """Return local crate-name -> Cargo manifest dir for the active project root."""
    root = find_workspace_root(scan_root) if scan_root is not None else get_project_root()
    return _build_workspace_package_index_cached(root)


@functools.lru_cache(maxsize=8)
def _build_workspace_package_index_cached(root: Path) -> dict[str, Path]:
    """Cached inner implementation of workspace package index building."""
    _exclusions = set(RUST_FILE_EXCLUSIONS)
    packages: dict[str, Path] = {}
    for manifest in root.rglob("Cargo.toml"):
        if any(part in _exclusions for part in manifest.relative_to(root).parts[:-1]):
            continue
        manifest_dir = manifest.parent.resolve()
        for name in {
            read_package_name(manifest_dir),
            read_library_crate_name(manifest_dir),
        }:
            if name:
                packages[name] = manifest_dir
    return packages


@functools.lru_cache(maxsize=64)
def _build_local_dependency_alias_index_cached(
    normalized_manifest_dir: Path,
    workspace_root: Path,
    package_index_items: tuple[tuple[str, str], ...],
) -> dict[str, Path]:
    """Cached implementation of local dependency alias extraction.

    Keying on primitive tuples keeps the cache hashable while preserving exact
    package_index state for correctness.
    """
    package_index: dict[str, Path] = {
        name: Path(manifest_dir)
        for name, manifest_dir in package_index_items
    }
    workspace_aliases = _workspace_dependency_alias_index(workspace_root, package_index)
    aliases: dict[str, Path] = {}
    data = _read_manifest_data(normalized_manifest_dir)
    for alias, dependency in _iter_dependency_entries(data):
        alias_name = normalize_crate_name(alias)
        if not alias_name or not isinstance(dependency, dict):
            continue
        resolved = _resolve_local_dependency_entry(
            alias_name=alias_name,
            dependency=dependency,
            base_dir=normalized_manifest_dir,
            package_index=package_index,
            workspace_aliases=workspace_aliases,
        )
        if resolved is not None:
            aliases[alias_name] = resolved
    return aliases


def build_local_dependency_alias_index(
    manifest_dir: Path,
    package_index: dict[str, Path] | None = None,
) -> dict[str, Path]:
    """Map local dependency aliases usable from one manifest to their crate roots."""
    normalized_manifest_dir = manifest_dir.resolve()
    workspace_root = find_workspace_root(normalized_manifest_dir)
    package_index = package_index or build_workspace_package_index(workspace_root)
    package_index_items = tuple(
        sorted((name, str(path.resolve())) for name, path in package_index.items())
    )
    return _build_local_dependency_alias_index_cached(
        normalized_manifest_dir,
        workspace_root,
        package_index_items,
    )


def _workspace_dependency_alias_index(
    workspace_root: Path,
    package_index: dict[str, Path],
) -> dict[str, Path]:
    data = _read_manifest_data(workspace_root)
    workspace = data.get("workspace")
    if not isinstance(workspace, dict):
        return {}
    dependencies = workspace.get("dependencies")
    if not isinstance(dependencies, dict):
        return {}

    aliases: dict[str, Path] = {}
    for alias, dependency in dependencies.items():
        alias_name = normalize_crate_name(alias)
        if not alias_name or not isinstance(dependency, dict):
            continue
        resolved = _resolve_local_dependency_entry(
            alias_name=alias_name,
            dependency=dependency,
            base_dir=workspace_root,
            package_index=package_index,
            workspace_aliases={},
        )
        if resolved is not None:
            aliases[alias_name] = resolved
    return aliases


def _iter_dependency_entries(data: dict[str, Any]) -> list[tuple[str, Any]]:
    entries: list[tuple[str, Any]] = []
    for section_name in ("dependencies", "dev-dependencies", "build-dependencies"):
        section = data.get(section_name)
        if isinstance(section, dict):
            entries.extend((str(name), value) for name, value in section.items())
    target = data.get("target")
    if isinstance(target, dict):
        for target_section in target.values():
            if not isinstance(target_section, dict):
                continue
            for section_name in ("dependencies", "dev-dependencies", "build-dependencies"):
                section = target_section.get(section_name)
                if isinstance(section, dict):
                    entries.extend((str(name), value) for name, value in section.items())
    return entries


def _resolve_local_dependency_entry(
    alias_name: str,
    dependency: dict[str, Any],
    *,
    base_dir: Path,
    package_index: dict[str, Path],
    workspace_aliases: dict[str, Path],
) -> Path | None:
    path_value = dependency.get("path")
    if isinstance(path_value, str) and path_value.strip():
        candidate = (base_dir / path_value).resolve()
        if (candidate / "Cargo.toml").is_file():
            return candidate

    if dependency.get("workspace") is True:
        package_name = normalize_crate_name(dependency.get("package"))
        if package_name and package_name in package_index:
            return package_index[package_name]
        return workspace_aliases.get(alias_name)

    package_name = normalize_crate_name(dependency.get("package"))
    if package_name and package_name in package_index and dependency.get("path") is not None:
        return package_index[package_name]
    return None


def find_workspace_root(path: Path | str | None) -> Path:
    """Return the outermost Cargo workspace root for a file/dir when present."""
    if path is None:
        return get_project_root()

    candidate = Path(resolve_path(str(path))).resolve()
    if candidate.is_file():
        candidate = candidate.parent
    manifest_dir = find_manifest_dir(candidate) or candidate
    workspace_root = manifest_dir
    for current in (manifest_dir, *manifest_dir.parents):
        manifest = current / "Cargo.toml"
        if not manifest.is_file():
            continue
        data = _load_toml_dict(manifest)
        if data is None:
            continue
        workspace = data.get("workspace")
        if isinstance(workspace, dict):
            workspace_root = current
    return workspace_root.resolve()


def describe_rust_file(source_file: str | Path) -> RustFileContext:
    """Build resolution context for a Rust source file."""
    source = Path(resolve_path(str(source_file))).resolve()
    manifest_dir = find_manifest_dir(source) or get_project_root()
    package_name = read_package_name(manifest_dir)
    library_crate_name = read_library_crate_name(manifest_dir)
    try:
        rel_to_manifest = source.relative_to(manifest_dir)
    except ValueError:
        rel_to_manifest = source.name
        rel_to_manifest = Path(rel_to_manifest)

    parts = rel_to_manifest.parts
    if rel_to_manifest == Path("build.rs"):
        return RustFileContext(
            source_file=source,
            manifest_dir=manifest_dir,
            package_name=package_name,
            crate_name=normalize_crate_name(package_name or manifest_dir.name),
            source_root=manifest_dir,
            root_files=(manifest_dir / "build.rs",),
            module_segments=(),
        )

    if parts[:2] == ("src", "bin") and len(parts) >= 3:
        bin_name = Path(parts[2]).stem
        bin_dir = manifest_dir / "src" / "bin" / bin_name
        root_files = (
            manifest_dir / "src" / "bin" / f"{bin_name}.rs",
            bin_dir / "main.rs",
        )
        if len(parts) == 3:
            module_segments: tuple[str, ...] = ()
        else:
            module_segments = _module_segments_from_rel(Path(*parts[3:]))
        return RustFileContext(
            source_file=source,
            manifest_dir=manifest_dir,
            package_name=package_name,
            crate_name=normalize_crate_name(bin_name),
            source_root=bin_dir,
            root_files=root_files,
            module_segments=module_segments,
        )

    if parts[:1] == ("src",):
        crate_name = package_name if rel_to_manifest == Path("src/main.rs") else library_crate_name
        return RustFileContext(
            source_file=source,
            manifest_dir=manifest_dir,
            package_name=package_name,
            crate_name=crate_name,
            source_root=manifest_dir / "src",
            root_files=(
                manifest_dir / "src" / "lib.rs",
                manifest_dir / "src" / "main.rs",
            ),
            module_segments=_module_segments_from_rel(Path(*parts[1:])),
        )

    if parts[:1] in {("tests",), ("examples",), ("benches",)} and len(parts) >= 2:
        root_name = Path(parts[1]).stem
        bucket = parts[0]
        root_dir = manifest_dir / bucket / root_name
        return RustFileContext(
            source_file=source,
            manifest_dir=manifest_dir,
            package_name=package_name,
            crate_name=normalize_crate_name(root_name),
            source_root=root_dir,
            root_files=(
                manifest_dir / bucket / f"{root_name}.rs",
                root_dir / "main.rs",
            ),
            module_segments=() if len(parts) == 2 else _module_segments_from_rel(Path(*parts[2:])),
        )

    return RustFileContext(
        source_file=source,
        manifest_dir=manifest_dir,
        package_name=package_name,
        crate_name=package_name,
        source_root=source.parent,
        root_files=(source,),
        module_segments=(),
    )


def resolve_mod_declaration(
    module_name: str,
    source_file: str | Path,
    production_files: set[str],
    *,
    declared_path: str | None = None,
    production_index: RustProductionFileIndex | None = None,
) -> str | None:
    """Resolve `mod foo;` to `foo.rs` or `foo/mod.rs` relative to the file's module dir."""
    source = Path(resolve_path(str(source_file))).resolve()
    base_dir = (
        source.parent
        if source.name in {"lib.rs", "main.rs", "mod.rs", "build.rs"}
        else source.with_suffix("")
    )
    candidates: list[Path] = []
    if declared_path:
        candidates.append(source.parent / declared_path)
    candidates.extend((base_dir / f"{module_name}.rs", base_dir / module_name / "mod.rs"))
    for candidate in candidates:
        matched = _candidate_matches(
            candidate,
            production_files,
            production_index=production_index,
        )
        if matched:
            return matched
    return None


def resolve_use_spec(
    spec: str,
    source_file: str | Path,
    production_files: set[str],
    package_index: dict[str, Path] | None = None,
    *,
    allow_crate_root_fallback: bool = True,
    production_index: RustProductionFileIndex | None = None,
) -> str | None:
    """Resolve a Rust `use` spec to a local module file when possible."""
    cleaned = _normalize_use_spec(spec)
    if not cleaned:
        return None

    package_index = package_index or build_workspace_package_index()
    context = describe_rust_file(source_file)
    dependency_aliases = build_local_dependency_alias_index(
        context.manifest_dir,
        package_index,
    )
    segments = [segment for segment in cleaned.split("::") if segment]
    if not segments:
        return None

    candidates: list[str | None] = []
    if cleaned.startswith("crate::"):
        candidates.append(
            _resolve_from_source_root(
                context.source_root,
                context.root_files,
                segments[1:],
                production_files,
                production_index=production_index,
                allow_root_fallback=allow_crate_root_fallback,
            )
        )
    elif segments[0] in {"self", "super"}:
        resolved_segments = _resolve_relative_segments(context.module_segments, segments)
        candidates.append(
            _resolve_from_source_root(
                context.source_root,
                context.root_files,
                resolved_segments,
                production_files,
                production_index=production_index,
                allow_root_fallback=allow_crate_root_fallback,
            )
        )
    else:
        first = normalize_crate_name(segments[0]) or segments[0]
        manifest_dir = dependency_aliases.get(first) or package_index.get(first)
        if manifest_dir is not None:
            lib_root = manifest_dir / "src"
            candidates.append(
                _resolve_from_source_root(
                    lib_root,
                    (manifest_dir / "src" / "lib.rs", manifest_dir / "src" / "main.rs"),
                    segments[1:],
                    production_files,
                    production_index=production_index,
                    allow_root_fallback=allow_crate_root_fallback,
                )
            )
        candidates.append(
            _resolve_from_source_root(
                context.source_root,
                context.root_files,
                list(context.module_segments) + segments,
                production_files,
                production_index=production_index,
                allow_root_fallback=False,
            )
        )
        candidates.append(
            _resolve_from_source_root(
                context.source_root,
                context.root_files,
                segments,
                production_files,
                production_index=production_index,
                allow_root_fallback=allow_crate_root_fallback,
            )
        )

    for resolved in candidates:
        if resolved:
            return resolved
    return None


def resolve_barrel_targets(
    filepath: str | Path,
    production_files: set[str],
    package_index: dict[str, Path] | None = None,
    production_index: RustProductionFileIndex | None = None,
) -> set[str]:
    """Resolve `pub use` / `pub mod` targets from a Rust facade file."""
    try:
        content = Path(resolve_path(str(filepath))).read_text(errors="replace")
    except OSError:
        return set()

    package_index = package_index or build_workspace_package_index()
    targets: set[str] = set()
    for spec in iter_pub_use_specs(content):
        resolved = resolve_use_spec(
            spec,
            filepath,
            production_files,
            package_index,
            allow_crate_root_fallback=False,
            production_index=production_index,
        )
        if resolved:
            targets.add(resolved)
    for module_name, declared_path in iter_mod_targets(content):
        resolved = resolve_mod_declaration(
            module_name,
            filepath,
            production_files,
            declared_path=declared_path,
            production_index=production_index,
        )
        if resolved:
            targets.add(resolved)
    return targets


def _module_segments_from_rel(rel_path: Path) -> tuple[str, ...]:
    parts = list(rel_path.parts)
    if not parts:
        return ()
    filename = parts[-1]
    if filename in {"lib.rs", "main.rs"} and len(parts) == 1:
        return ()
    if filename == "mod.rs":
        return tuple(parts[:-1])
    if filename.endswith(".rs"):
        return tuple(parts[:-1] + [Path(filename).stem])
    return tuple(parts)


def _resolve_relative_segments(
    module_segments: tuple[str, ...],
    segments: list[str],
) -> list[str]:
    resolved = list(module_segments)
    remaining = list(segments)
    while remaining and remaining[0] in {"self", "super"}:
        head = remaining.pop(0)
        if head == "super" and resolved:
            resolved.pop()
    resolved.extend(remaining)
    return resolved


def _resolve_from_source_root(
    source_root: Path,
    root_files: tuple[Path, ...],
    segments: list[str],
    production_files: set[str],
    *,
    production_index: RustProductionFileIndex | None,
    allow_root_fallback: bool,
) -> str | None:
    if not segments:
        return _match_root_files(
            root_files,
            production_files,
            production_index=production_index,
        )

    for width in range(len(segments), 0, -1):
        module_parts = segments[:width]
        if not module_parts:
            continue
        file_candidate = source_root.joinpath(*module_parts).with_suffix(".rs")
        mod_candidate = source_root.joinpath(*module_parts, "mod.rs")
        for candidate in (file_candidate, mod_candidate):
            matched = _candidate_matches(
                candidate,
                production_files,
                production_index=production_index,
            )
            if matched:
                return matched

    if allow_root_fallback:
        return _match_root_files(
            root_files,
            production_files,
            production_index=production_index,
        )
    return None


def _match_root_files(
    root_files: tuple[Path, ...],
    production_files: set[str],
    *,
    production_index: RustProductionFileIndex | None,
) -> str | None:
    for root_file in root_files:
        matched = _candidate_matches(
            root_file,
            production_files,
            production_index=production_index,
        )
        if matched:
            return matched
    return None


def _candidate_matches(
    candidate: Path,
    production_files: set[str],
    *,
    production_index: RustProductionFileIndex | None = None,
) -> str | None:
    index = production_index or build_production_file_index(production_files)
    resolved_candidate = candidate.resolve()
    candidate_abs = str(resolved_candidate)
    absolute_match = index.by_absolute.get(candidate_abs)
    if absolute_match is not None:
        return absolute_match
    try:
        candidate_rel = rel(resolved_candidate, project_root=index.project_root)
    except (TypeError, ValueError, OSError):
        candidate_rel = None
    if candidate_rel is not None:
        relative_match = index.by_relative.get(candidate_rel)
        if relative_match is not None:
            return relative_match
    return None


def match_production_candidate(candidate: Path, production_files: set[str]) -> str | None:
    """Public wrapper for matching a resolved candidate to the production-file set."""
    return _candidate_matches(candidate, production_files)


def _split_top_level(text: str, delimiter: str = ",") -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in text:
        if char in "{([":
            depth += 1
        elif char in "})]":
            depth = max(0, depth - 1)
        if char == delimiter and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _expand_use_tree(spec: str) -> list[str]:
    spec = spec.strip()
    if not spec:
        return []

    alias_split = re.split(r"\s+as\s+", spec, maxsplit=1)
    spec = alias_split[0].strip()
    if not spec:
        return []

    open_index = spec.find("{")
    if open_index == -1:
        normalized = _normalize_use_spec(spec)
        return [normalized] if normalized else []

    close_index = _find_matching_brace(spec, open_index)
    if close_index is None:
        normalized = _normalize_use_spec(spec)
        return [normalized] if normalized else []

    prefix = spec[:open_index].rstrip(":")
    suffix = spec[close_index + 1 :].strip()
    inner = spec[open_index + 1 : close_index]
    expanded: list[str] = []
    for part in _split_top_level(inner):
        combined = part if not prefix else f"{prefix}::{part}"
        if suffix:
            combined = f"{combined}{suffix}"
        expanded.extend(_expand_use_tree(combined))
    return expanded


def _find_matching_brace(text: str, start_index: int) -> int | None:
    depth = 0
    for index in range(start_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _normalize_use_spec(spec: str) -> str | None:
    normalized = spec.strip().replace(" ", "")
    if not normalized:
        return None
    normalized = normalized.removeprefix("::")
    normalized = normalized.replace("::{self}", "")
    normalized = normalized.replace("::self", "")
    normalized = normalized.replace("::*", "")
    normalized = normalized.strip(":")
    return normalized or None


def _path_override_from_attrs(attrs: list[str]) -> str | None:
    for attr in reversed(attrs):
        match = _PATH_ATTR_RE.search(attr)
        if match:
            value = match.group(1).strip()
            if value:
                return value
    return None


def _load_toml_dict(path: Path) -> dict[str, Any] | None:
    """Parse a TOML file into a dictionary when possible."""
    text = read_text_or_none(path)
    if text is None:
        return None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    return data if isinstance(data, dict) else None


__all__ = [
    "RUST_FILE_EXCLUSIONS",
    "PUB_USE_STATEMENT_RE",
    "RustFileContext",
    "RustProductionFileIndex",
    "USE_STATEMENT_RE",
    "build_production_file_index",
    "build_workspace_package_index",
    "build_local_dependency_alias_index",
    "describe_rust_file",
    "find_manifest_dir",
    "find_rust_files",
    "find_workspace_root",
    "has_public_api_markers",
    "iter_mod_declarations",
    "iter_mod_targets",
    "iter_pub_use_specs",
    "iter_use_specs",
    "match_production_candidate",
    "normalize_crate_name",
    "normalize_rust_body",
    "read_text_or_none",
    "read_library_crate_name",
    "read_package_name",
    "resolve_barrel_targets",
    "resolve_mod_declaration",
    "resolve_use_spec",
    "strip_rust_comments",
]
