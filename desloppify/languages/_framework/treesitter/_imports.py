"""Tree-sitter based import extraction and dep graph builder."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ._cache import _PARSE_CACHE
from ._extractors import _get_parser, _make_query, _run_query, _unwrap_node

if TYPE_CHECKING:
    from desloppify.languages._framework.treesitter import TreeSitterLangSpec

logger = logging.getLogger(__name__)


def ts_build_dep_graph(
    path: Path,
    spec: TreeSitterLangSpec,
    file_list: list[str],
) -> dict[str, dict]:
    """Build a dependency graph by parsing imports with tree-sitter.

    Returns the same shape as Python/TS dep graphs:
    {file: {"imports": set[str], "importers": set[str], "import_count": int, "importer_count": int}}
    """
    if not spec.import_query or not spec.resolve_import:
        return {}

    parser, language = _get_parser(spec.grammar)
    query = _make_query(language, spec.import_query)

    scan_path = str(path.resolve())
    file_set = set(file_list)
    graph: dict[str, dict] = {}

    # Initialize all files in the graph.
    for f in file_list:
        graph[f] = {"imports": set(), "importers": set()}

    for filepath in file_list:
        cached = _PARSE_CACHE.get_or_parse(filepath, parser, spec.grammar)
        if cached is None:
            continue
        _source, tree = cached
        matches = _run_query(query, tree.root_node)

        for _pattern_idx, captures in matches:
            path_node = _unwrap_node(captures.get("path"))
            if not path_node:
                continue

            raw_text = path_node.text
            import_text = (
                raw_text.decode("utf-8", errors="replace")
                if isinstance(raw_text, bytes)
                else str(raw_text)
            )

            # Strip surrounding quotes if present.
            import_text = import_text.strip("\"'`")

            # Prepend group-use prefix when present (PHP ``use A\B\{C, D}``).
            prefix_node = _unwrap_node(captures.get("prefix"))
            if prefix_node is not None:
                prefix_raw = prefix_node.text
                prefix_text = (
                    prefix_raw.decode("utf-8", errors="replace")
                    if isinstance(prefix_raw, bytes)
                    else str(prefix_raw)
                ).strip("\"'`")
                import_text = f"{prefix_text}\\{import_text}"

            resolved = spec.resolve_import(import_text, filepath, scan_path)
            if resolved is None:
                continue

            # Normalize to absolute path.
            if not os.path.isabs(resolved):
                resolved = os.path.normpath(os.path.join(scan_path, resolved))

            # Only track edges within the scanned file set.
            if resolved not in file_set:
                continue

            graph[filepath]["imports"].add(resolved)
            if resolved in graph:
                graph[resolved]["importers"].add(filepath)

    # Finalize: add counts.
    for data in graph.values():
        data["import_count"] = len(data["imports"])
        data["importer_count"] = len(data["importers"])

    return graph


def make_ts_dep_builder(spec: TreeSitterLangSpec, file_finder):
    """Create a dep graph builder bound to a TreeSitterLangSpec + file finder.

    Returns a callable with signature (path: Path) -> dict,
    matching the contract expected by LangConfig.build_dep_graph.
    """

    def build(path: Path) -> dict:
        file_list = file_finder(path)
        return ts_build_dep_graph(path, spec, file_list)

    return build


# ── Per-language import resolvers ─────────────────────────────


def resolve_go_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Go imports to local files.

    Go imports are module paths like "myproject/pkg/foo". We need the go.mod
    module path to determine if an import is local, then map it to a file.
    """
    # Skip standard library and common external packages.
    if not import_text or "/" not in import_text:
        return None  # stdlib (e.g. "fmt", "os")

    # Read go.mod to get module path.
    go_mod = os.path.join(scan_path, "go.mod")
    module_path = _read_go_module_path(go_mod)
    if not module_path:
        return None

    if not import_text.startswith(module_path):
        return None  # external package

    # Map module-relative import to filesystem path.
    rel_path = import_text[len(module_path) :].lstrip("/")
    candidate_dir = os.path.join(scan_path, rel_path)

    # Go imports point to packages (directories), not files.
    # Return the directory — the coupling detector works with directories.
    if os.path.isdir(candidate_dir):
        # Find the first .go file in the package dir.
        for f in sorted(os.listdir(candidate_dir)):
            if f.endswith(".go") and not f.endswith("_test.go"):
                return os.path.join(candidate_dir, f)
    return None


_GO_MODULE_CACHE: dict[str, str] = {}


def _read_go_module_path(go_mod_path: str) -> str:
    """Read module path from go.mod, caching the result."""
    if go_mod_path in _GO_MODULE_CACHE:
        return _GO_MODULE_CACHE[go_mod_path]

    module_path = ""
    try:
        with open(go_mod_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("module "):
                    module_path = line.split(None, 1)[1].strip()
                    break
    except OSError as exc:
        logger.debug("Failed to read go.mod at %s: %s", go_mod_path, exc)
    _GO_MODULE_CACHE[go_mod_path] = module_path
    return module_path


def resolve_rust_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Rust `use` declarations to local files.

    Handles `crate::module::item` → src/module.rs or src/module/mod.rs.
    """
    if not import_text.startswith("crate::"):
        return None  # external crate or std

    parts = import_text[len("crate::") :].split("::")
    if not parts:
        return None

    src_dir = os.path.join(scan_path, "src")
    if not os.path.isdir(src_dir):
        src_dir = scan_path

    # Try file path: src/a/b.rs
    path_parts = parts[:-1] if len(parts) > 1 else parts
    candidate = os.path.join(src_dir, *path_parts) + ".rs"
    if os.path.isfile(candidate):
        return candidate

    # Try directory path: src/a/b/mod.rs
    candidate = os.path.join(src_dir, *path_parts, "mod.rs")
    if os.path.isfile(candidate):
        return candidate

    # Try with all parts as path.
    candidate = os.path.join(src_dir, *parts) + ".rs"
    if os.path.isfile(candidate):
        return candidate

    return None


def resolve_ruby_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Ruby require/require_relative to local files."""
    if import_text.startswith("./") or import_text.startswith("../"):
        # require_relative — resolve relative to source file.
        base = os.path.dirname(source_file)
        candidate = os.path.normpath(os.path.join(base, import_text))
        if not candidate.endswith(".rb"):
            candidate += ".rb"
        if os.path.isfile(candidate):
            return candidate
        return None

    # Regular require — try relative to lib/ or scan_path.
    for base in [os.path.join(scan_path, "lib"), scan_path]:
        candidate = os.path.join(base, import_text.replace("/", os.sep))
        if not candidate.endswith(".rb"):
            candidate += ".rb"
        if os.path.isfile(candidate):
            return candidate

    return None


def resolve_java_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Java imports to local files.

    Maps `com.example.Foo` → find Foo.java under source roots.
    """
    # Skip wildcard imports.
    if import_text.endswith(".*"):
        return None

    parts = import_text.split(".")
    if len(parts) < 2:
        return None

    # The last part is the class name, preceding parts are the package path.
    rel_path = os.path.join(*parts[:-1], parts[-1] + ".java")

    # Search common source roots.
    for src_root in [
        "src/main/java", "src", "app/src/main/java", ".",
    ]:
        candidate = os.path.join(scan_path, src_root, rel_path)
        if os.path.isfile(candidate):
            return candidate

    return None


def resolve_kotlin_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Kotlin imports — same logic as Java but with .kt extension."""
    if import_text.endswith(".*"):
        return None

    parts = import_text.split(".")
    if len(parts) < 2:
        return None

    for ext in (".kt", ".kts"):
        rel_path = os.path.join(*parts[:-1], parts[-1] + ext)
        for src_root in [
            "src/main/kotlin", "src/main/java", "src", "app/src/main/kotlin", ".",
        ]:
            candidate = os.path.join(scan_path, src_root, rel_path)
            if os.path.isfile(candidate):
                return candidate

    return None


def resolve_cxx_include(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve C/C++ #include "local.h" to local files.

    Only resolves quoted includes (not angle-bracket system includes).
    """
    # import_text comes from the query as the header path (without quotes).
    if not import_text:
        return None

    # Try relative to source file first.
    base = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(base, import_text))
    if os.path.isfile(candidate):
        return candidate

    # Try relative to common include directories.
    for inc_dir in ["include", "src", "."]:
        candidate = os.path.join(scan_path, inc_dir, import_text)
        if os.path.isfile(candidate):
            return candidate

    return None


_PHP_FILE_CACHE: dict[tuple[str, str], str | None] = {}


def _find_php_file(filename: str, scan_path: str) -> str | None:
    """Search common PHP source roots for *filename*, cached."""
    key = (filename, scan_path)
    if key in _PHP_FILE_CACHE:
        return _PHP_FILE_CACHE[key]
    for root in ("app", "src", "lib"):
        root_dir = os.path.join(scan_path, root)
        if not os.path.isdir(root_dir):
            continue
        for dirpath, _dirs, files in os.walk(root_dir):
            if filename in files:
                result = os.path.join(dirpath, filename)
                _PHP_FILE_CACHE[key] = result
                return result
    _PHP_FILE_CACHE[key] = None
    return None


_PHP_COMPOSER_CACHE: dict[str, dict[str, str]] = {}


def _read_composer_psr4(scan_path: str) -> dict[str, str]:
    """Read PSR-4 autoload mappings from composer.json, cached per scan_path.

    Returns ``{namespace_prefix: directory}`` e.g. ``{"App\\\\": "app/"}``.
    """
    if scan_path in _PHP_COMPOSER_CACHE:
        return _PHP_COMPOSER_CACHE[scan_path]

    mappings: dict[str, str] = {}
    composer_path = os.path.join(scan_path, "composer.json")
    try:
        import json

        with open(composer_path) as f:
            data = json.load(f)
        for section in ("autoload", "autoload-dev"):
            psr4 = data.get(section, {}).get("psr-4", {})
            for prefix, dirs in psr4.items():
                # dirs can be a string or list of strings
                if isinstance(dirs, str):
                    mappings[prefix] = dirs
                elif isinstance(dirs, list) and dirs:
                    mappings[prefix] = dirs[0]
    except (OSError, ValueError, KeyError):
        pass
    _PHP_COMPOSER_CACHE[scan_path] = mappings
    return mappings


def resolve_php_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve PHP use statements via PSR-4 mapping.

    1. Reads composer.json autoload psr-4 mappings (cached).
    2. Falls back to common PSR-4 roots (src/, app/, lib/).
    3. For bare trait names, searches common directories for ``Name.php``.

    Maps ``App\\Models\\User`` → ``app/Models/User.php``.
    """
    # Strip leading backslash from FQNs (e.g. ``\App\Traits\HasRoles``).
    import_text = import_text.lstrip("\\")

    parts = import_text.replace("\\", "/").split("/")

    # Bare name (e.g. trait ``use HasUuid;``) — search common dirs.
    if len(parts) < 2:
        name = parts[0] if parts else ""
        if not name or not name[0].isupper():
            return None
        return _find_php_file(name + ".php", scan_path)


    # Try composer.json PSR-4 mappings first.
    psr4 = _read_composer_psr4(scan_path)
    if psr4:
        # Reconstruct backslash-separated namespace for prefix matching.
        ns = import_text.replace("/", "\\")
        if not ns.endswith("\\"):
            ns_lookup = ns
        else:
            ns_lookup = ns

        for prefix, directory in sorted(psr4.items(), key=lambda x: -len(x[0])):
            # Normalize prefix: ensure trailing backslash
            norm_prefix = prefix.rstrip("\\") + "\\"
            if ns_lookup.startswith(norm_prefix) or ns_lookup + "\\" == norm_prefix:
                remainder = ns_lookup[len(norm_prefix):]
                if not remainder:
                    continue
                rel_path = remainder.replace("\\", os.sep) + ".php"
                candidate = os.path.join(scan_path, directory, rel_path)
                candidate = os.path.normpath(candidate)
                if os.path.isfile(candidate):
                    return candidate

    # Fallback: try common PSR-4 roots by stripping namespace prefixes.
    for prefix_len in range(1, min(3, len(parts))):
        rel_path = os.path.join(*parts[prefix_len:]) + ".php"
        for src_root in ["src", "app", "lib", "."]:
            candidate = os.path.join(scan_path, src_root, rel_path)
            if os.path.isfile(candidate):
                return candidate

    return None


def resolve_elixir_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Elixir aliases to local files.

    Maps `MyApp.Module.Sub` → lib/my_app/module/sub.ex.
    """
    parts = import_text.split(".")
    if len(parts) < 2:
        return None

    # Convert CamelCase parts to snake_case for file path.
    snake_parts = [_camel_to_snake(p) for p in parts]

    rel_path = os.path.join(*snake_parts) + ".ex"
    candidate = os.path.join(scan_path, "lib", rel_path)
    if os.path.isfile(candidate):
        return candidate

    # Try without the app-level prefix.
    if len(snake_parts) > 1:
        rel_path = os.path.join(*snake_parts[1:]) + ".ex"
        candidate = os.path.join(scan_path, "lib", snake_parts[0], rel_path)
        if os.path.isfile(candidate):
            return candidate

    return None


def resolve_lua_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Lua require("foo.bar") to local files."""
    if not import_text:
        return None

    # Replace dots with path separators.
    rel_path = import_text.replace(".", os.sep) + ".lua"
    candidate = os.path.join(scan_path, rel_path)
    if os.path.isfile(candidate):
        return candidate

    # Try init.lua for packages.
    candidate = os.path.join(scan_path, import_text.replace(".", os.sep), "init.lua")
    if os.path.isfile(candidate):
        return candidate

    return None


def resolve_swift_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Swift uses module-level imports — not resolvable to individual files."""
    return None


def resolve_scala_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Scala imports — similar to Java."""
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


def resolve_csharp_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve C# using statements to local files.

    Maps `MyApp.Models.User` → find User.cs under source roots.
    """
    parts = import_text.split(".")
    if len(parts) < 2:
        return None

    # Try the last part as filename.
    filename = parts[-1] + ".cs"
    for src_root in ["src", ".", "lib"]:
        # Try with namespace as directory structure.
        rel_path = os.path.join(*parts[:-1], filename)
        candidate = os.path.join(scan_path, src_root, rel_path)
        if os.path.isfile(candidate):
            return candidate
        # Try flat (just the filename in src root).
        candidate = os.path.join(scan_path, src_root, filename)
        if os.path.isfile(candidate):
            return candidate

    return None


def resolve_dart_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Dart imports to local files.

    Handles `package:myapp/models/user.dart` and relative imports.
    """
    if import_text.startswith("dart:"):
        return None  # SDK import

    if import_text.startswith("package:"):
        # Extract path after package:name/
        parts = import_text[len("package:") :].split("/", 1)
        if len(parts) < 2:
            return None
        rel_path = parts[1]
        candidate = os.path.join(scan_path, "lib", rel_path)
        if os.path.isfile(candidate):
            return candidate
        return None

    # Relative import.
    base = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(base, import_text))
    if os.path.isfile(candidate):
        return candidate
    return None


def resolve_js_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve JS/ESM imports to local files.

    Only resolves relative imports (starting with . or ..).
    """
    if not import_text or not import_text.startswith("."):
        return None  # npm package

    base = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(base, import_text))

    # Try extensions: .js, .jsx, .mjs, .cjs, /index.js, /index.jsx
    for ext in ("", ".js", ".jsx", ".mjs", ".cjs", "/index.js", "/index.jsx"):
        path = candidate + ext
        if os.path.isfile(path):
            return path
    return None


def resolve_bash_source(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Bash source/. commands to local files.

    Handles `source ./foo.sh` and `. ./bar.sh`.
    """
    if not import_text:
        return None

    # Strip quotes if present.
    text = import_text.strip("\"'")

    # Resolve relative to source file directory.
    base = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(base, text))
    if os.path.isfile(candidate):
        return candidate

    # Try adding .sh extension.
    if not candidate.endswith(".sh"):
        if os.path.isfile(candidate + ".sh"):
            return candidate + ".sh"

    # Try relative to scan path.
    candidate = os.path.normpath(os.path.join(scan_path, text))
    if os.path.isfile(candidate):
        return candidate

    return None


# Perl pragmas and core modules to skip.
_PERL_SKIP_MODULES = frozenset({
    "strict", "warnings", "utf8", "lib", "constant", "Exporter", "Carp",
    "POSIX", "English", "Data::Dumper", "Storable", "Encode",
    "overload", "parent", "base", "vars", "feature", "mro",
})
_PERL_SKIP_PREFIXES = ("File::", "List::", "Scalar::", "Getopt::", "IO::", "Test::")


def resolve_perl_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Perl `use MyApp::Model::User` to local files.

    Converts `MyApp::Model::User` to `MyApp/Model/User.pm`.
    Searches in `lib/` then scan root.
    """
    if not import_text:
        return None

    # Skip pragmas and core modules.
    if import_text in _PERL_SKIP_MODULES:
        return None
    if any(import_text.startswith(p) for p in _PERL_SKIP_PREFIXES):
        return None

    # Convert :: to path separator.
    rel_path = import_text.replace("::", os.sep) + ".pm"

    for base in [os.path.join(scan_path, "lib"), scan_path]:
        candidate = os.path.join(base, rel_path)
        if os.path.isfile(candidate):
            return candidate

    return None


def resolve_zig_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Zig `@import("utils.zig")` to local files.

    Skips `"std"` and `"builtin"`. Resolves relative to source file.
    """
    if not import_text:
        return None

    # Strip quotes.
    text = import_text.strip('"')

    # Skip standard library.
    if text in ("std", "builtin"):
        return None

    # Resolve relative to source file directory.
    base = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(base, text))
    if os.path.isfile(candidate):
        return candidate

    # Try adding .zig extension.
    if not candidate.endswith(".zig"):
        if os.path.isfile(candidate + ".zig"):
            return candidate + ".zig"

    return None


# Haskell stdlib prefixes.
_HASKELL_STDLIB_PREFIXES = (
    "Data.", "Control.", "System.", "GHC.", "Text.", "Network.",
    "Foreign.", "Numeric.", "Debug.",
)


def resolve_haskell_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Haskell `import MyApp.Module` to local files.

    Converts dots to slashes, searches in `src/`, `lib/`, `app/`.
    Skips known stdlib prefixes.
    """
    if not import_text:
        return None

    # Skip stdlib modules.
    if any(import_text.startswith(p) for p in _HASKELL_STDLIB_PREFIXES):
        return None
    # Single-word stdlib modules.
    if import_text in ("Prelude", "Main"):
        return None

    # Convert dots to path separators.
    rel_path = import_text.replace(".", os.sep) + ".hs"

    for base_dir in ["src", "lib", "app", "."]:
        candidate = os.path.join(scan_path, base_dir, rel_path)
        if os.path.isfile(candidate):
            return candidate

    return None


def resolve_erlang_include(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Erlang -include("file.hrl") to local files.

    Resolves relative to source file, then tries include/ directory.
    """
    if not import_text:
        return None

    text = import_text.strip('"')

    # Resolve relative to source file directory.
    base = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(base, text))
    if os.path.isfile(candidate):
        return candidate

    # Try include/ directory.
    candidate = os.path.join(scan_path, "include", text)
    if os.path.isfile(candidate):
        return candidate

    # Try scan root.
    candidate = os.path.join(scan_path, text)
    if os.path.isfile(candidate):
        return candidate

    return None


# OCaml stdlib modules to skip.
_OCAML_STDLIB_MODULES = frozenset({
    "Stdlib", "List", "Array", "String", "Bytes", "Char", "Int", "Float",
    "Bool", "Unit", "Option", "Result", "Fun", "Seq", "Map", "Set",
    "Hashtbl", "Buffer", "Printf", "Format", "Scanf", "Sys", "Arg",
    "Filename", "Printexc", "Gc", "Lazy", "Stream", "Queue", "Stack",
    "Lexing", "Parsing", "Complex", "In_channel", "Out_channel",
})


def resolve_ocaml_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve OCaml `open MyModule` to local files.

    Converts module name to lowercase filename with .ml extension.
    """
    if not import_text:
        return None

    # Skip stdlib modules.
    top_module = import_text.split(".")[0]
    if top_module in _OCAML_STDLIB_MODULES:
        return None

    # Convert module name to lowercase filename.
    # MyModule -> my_module.ml (OCaml convention: lowercase filenames)
    parts = import_text.split(".")
    filename = parts[-1].lower() + ".ml"

    # Search common directories.
    for base_dir in ["lib", "src", "."]:
        candidate = os.path.join(scan_path, base_dir, filename)
        if os.path.isfile(candidate):
            return candidate

    return None


# F# stdlib namespaces to skip.
_FSHARP_STDLIB_PREFIXES = (
    "System", "Microsoft", "FSharp",
)


def resolve_fsharp_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve F# `open MyApp.Module` to local files.

    Converts dots to path separators, searches in src/ and root.
    """
    if not import_text:
        return None

    # Skip stdlib namespaces.
    if any(import_text.startswith(p) for p in _FSHARP_STDLIB_PREFIXES):
        return None

    parts = import_text.split(".")
    if not parts:
        return None

    # Try last part as filename.
    filename = parts[-1] + ".fs"
    for base_dir in ["src", ".", "lib"]:
        # Try with namespace as directory structure.
        if len(parts) > 1:
            rel_path = os.path.join(*parts[:-1], filename)
            candidate = os.path.join(scan_path, base_dir, rel_path)
            if os.path.isfile(candidate):
                return candidate
        # Try flat (just filename).
        candidate = os.path.join(scan_path, base_dir, filename)
        if os.path.isfile(candidate):
            return candidate

    return None


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def resolve_r_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve R source() calls to local files.

    library() and require() load external CRAN packages — return None.
    source() loads local R scripts — resolve to path.
    """
    if not import_text:
        return None

    text = import_text.strip("\"'")

    # Only source() calls reference local files.
    # library("pkg") and require("pkg") are external packages.
    if not text.endswith((".R", ".r")):
        return None

    # Resolve relative to source file directory.
    base = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(base, text))
    if os.path.isfile(candidate):
        return candidate

    # Try relative to scan path (R/ subdirectory is standard for packages).
    for src_root in [".", "R"]:
        candidate = os.path.join(scan_path, src_root, text)
        if os.path.isfile(candidate):
            return candidate

    return None


__all__ = [
    "make_ts_dep_builder",
    "resolve_bash_source",
    "resolve_csharp_import",
    "resolve_cxx_include",
    "resolve_dart_import",
    "resolve_elixir_import",
    "resolve_erlang_include",
    "resolve_fsharp_import",
    "resolve_go_import",
    "resolve_haskell_import",
    "resolve_java_import",
    "resolve_js_import",
    "resolve_kotlin_import",
    "resolve_lua_import",
    "resolve_ocaml_import",
    "resolve_perl_import",
    "resolve_php_import",
    "resolve_ruby_import",
    "resolve_rust_import",
    "resolve_scala_import",
    "resolve_r_import",
    "resolve_swift_import",
    "resolve_zig_import",
    "ts_build_dep_graph",
]
