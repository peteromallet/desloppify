"""Import resolvers for scripting-oriented languages."""

from __future__ import annotations

import json
import os


def resolve_ruby_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Ruby require/require_relative to local files."""
    if import_text.startswith("./") or import_text.startswith("../"):
        base = os.path.dirname(source_file)
        candidate = os.path.normpath(os.path.join(base, import_text))
        if not candidate.endswith(".rb"):
            candidate += ".rb"
        return candidate if os.path.isfile(candidate) else None

    for base in [os.path.join(scan_path, "lib"), scan_path]:
        candidate = os.path.join(base, import_text.replace("/", os.sep))
        if not candidate.endswith(".rb"):
            candidate += ".rb"
        if os.path.isfile(candidate):
            return candidate
    return None


_PHP_FILE_CACHE: dict[tuple[str, str], str | None] = {}


def reset_script_import_caches(scan_path: str | None = None) -> None:
    """Reset cached script import resolution state globally or for one scan path."""
    if scan_path is None:
        _PHP_FILE_CACHE.clear()
        _PHP_COMPOSER_CACHE.clear()
        return

    normalized_scan_path = os.path.normpath(scan_path)
    stale_file_keys = [
        key for key in _PHP_FILE_CACHE
        if os.path.normpath(key[1]) == normalized_scan_path
    ]
    for key in stale_file_keys:
        _PHP_FILE_CACHE.pop(key, None)
    _PHP_COMPOSER_CACHE.pop(normalized_scan_path, None)


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
    normalized_scan_path = os.path.normpath(scan_path)
    if normalized_scan_path in _PHP_COMPOSER_CACHE:
        return _PHP_COMPOSER_CACHE[normalized_scan_path]

    mappings: dict[str, str] = {}
    composer_path = os.path.join(normalized_scan_path, "composer.json")
    if not os.path.isfile(composer_path):
        _PHP_COMPOSER_CACHE[normalized_scan_path] = mappings
        return mappings
    try:
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
    except (OSError, ValueError, TypeError, AttributeError):
        return mappings
    _PHP_COMPOSER_CACHE[normalized_scan_path] = mappings
    return mappings


def resolve_php_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve PHP use statements via PSR-4 mapping.

    1. Reads composer.json autoload psr-4 mappings (cached).
    2. Falls back to common PSR-4 roots (src/, app/, lib/).
    3. For bare trait names, searches common directories for ``Name.php``.

    Maps ``App\\Models\\User`` -> ``app/Models/User.php``.
    """
    del source_file
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


def resolve_lua_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Lua require(\"foo.bar\") to local files."""
    del source_file
    if not import_text:
        return None

    rel_path = import_text.replace(".", os.sep) + ".lua"
    candidate = os.path.join(scan_path, rel_path)
    if os.path.isfile(candidate):
        return candidate

    candidate = os.path.join(scan_path, import_text.replace(".", os.sep), "init.lua")
    if os.path.isfile(candidate):
        return candidate
    return None


def resolve_js_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve JS/ESM relative imports to local files."""
    del scan_path
    if not import_text or not import_text.startswith("."):
        return None

    base = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(base, import_text))
    for ext in ("", ".js", ".jsx", ".mjs", ".cjs", "/index.js", "/index.jsx"):
        path = candidate + ext
        if os.path.isfile(path):
            return path
    return None


def resolve_bash_source(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Bash source/. commands to local files."""
    if not import_text:
        return None

    text = import_text.strip("\"'")
    base = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(base, text))
    if os.path.isfile(candidate):
        return candidate
    if not candidate.endswith(".sh") and os.path.isfile(candidate + ".sh"):
        return candidate + ".sh"

    candidate = os.path.normpath(os.path.join(scan_path, text))
    return candidate if os.path.isfile(candidate) else None


_PERL_SKIP_MODULES = frozenset(
    {
        "strict",
        "warnings",
        "utf8",
        "lib",
        "constant",
        "Exporter",
        "Carp",
        "POSIX",
        "English",
        "Data::Dumper",
        "Storable",
        "Encode",
        "overload",
        "parent",
        "base",
        "vars",
        "feature",
        "mro",
    }
)
_PERL_SKIP_PREFIXES = ("File::", "List::", "Scalar::", "Getopt::", "IO::", "Test::")


def resolve_perl_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve Perl use My::Module to local .pm files."""
    del source_file
    if not import_text:
        return None
    if import_text in _PERL_SKIP_MODULES or any(
        import_text.startswith(prefix) for prefix in _PERL_SKIP_PREFIXES
    ):
        return None

    rel_path = import_text.replace("::", os.sep) + ".pm"
    for base in [os.path.join(scan_path, "lib"), scan_path]:
        candidate = os.path.join(base, rel_path)
        if os.path.isfile(candidate):
            return candidate
    return None


def resolve_r_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve R source() calls to local scripts."""
    if not import_text:
        return None

    text = import_text.strip("\"'")
    if not text.endswith((".R", ".r")):
        return None

    base = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(base, text))
    if os.path.isfile(candidate):
        return candidate

    for src_root in [".", "R"]:
        candidate = os.path.join(scan_path, src_root, text)
        if os.path.isfile(candidate):
            return candidate
    return None


# --- Luau require-by-string -------------------------------------------------
#
# Luau's require-by-string (Roblox, Lune, and the standalone luau CLI) takes a
# path string rather than a dotted module name:
#
#     require("./Sibling")            -- relative to the requiring file
#     require("../Types")             -- parent-relative
#     require("@self/Child")          -- the requiring module's own directory
#     require("@alias/Some/Module")   -- a .luaurc alias, or a host-provided
#                                        root such as Roblox's "@game"
#
# Host aliases such as "@game/ReplicatedStorage/Packages/Knit" address a runtime
# instance tree rather than the filesystem, and the mapping lives in a build
# manifest (a Rojo project file, for example) that is not part of the language.
# Rather than parse every possible manifest, unresolved alias tails are matched
# against an index of module paths under the scan root, longest tail first, and
# accepted only when exactly one file matches. That keeps the dependency graph
# free of guessed edges while still resolving the common case.

_LUAU_EXTENSIONS: tuple[str, ...] = (".luau", ".lua")

_LUAU_ALIAS_CACHE: dict[str, dict[str, str]] = {}
_LUAU_MODULE_INDEX_CACHE: dict[str, dict[str, list[str]]] = {}


def reset_luau_import_caches(scan_path: str | None = None) -> None:
    """Reset cached Luau alias and module-index state, globally or per scan path."""
    if scan_path is None:
        _LUAU_ALIAS_CACHE.clear()
        _LUAU_MODULE_INDEX_CACHE.clear()
        return

    normalized = os.path.normpath(scan_path)
    _LUAU_ALIAS_CACHE.pop(normalized, None)
    _LUAU_MODULE_INDEX_CACHE.pop(normalized, None)


def _luau_module_file(base_path: str) -> str | None:
    """Return the module file addressed by extension-less *base_path*, or None."""
    for ext in _LUAU_EXTENSIONS:
        candidate = base_path + ext
        if os.path.isfile(candidate):
            return candidate
    for ext in _LUAU_EXTENSIONS:
        candidate = os.path.join(base_path, "init" + ext)
        if os.path.isfile(candidate):
            return candidate
    return None


def _strip_luau_extension(path: str) -> str:
    """Strip a Luau source extension from *path*, leaving other names intact."""
    for ext in _LUAU_EXTENSIONS:
        if path.endswith(ext):
            return path[: -len(ext)]
    return path


def _strip_jsonc_comments(text: str) -> str:
    """Drop line comments from a JSON-with-comments document.

    A .luaurc is JSON5-ish in practice. Only line comments are common, and a
    naive strip would corrupt string literals that contain a double slash (a
    URL, for example), so strings are tracked while scanning.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if text[index : index + 2] == "//":
            while index < len(text) and text[index] != "\n":
                index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _read_luaurc_aliases(scan_path: str) -> dict[str, str]:
    """Read the alias table from the project .luaurc, cached per scan path."""
    normalized = os.path.normpath(scan_path)
    cached = _LUAU_ALIAS_CACHE.get(normalized)
    if cached is not None:
        return cached

    aliases: dict[str, str] = {}
    luaurc = os.path.join(normalized, ".luaurc")
    try:
        with open(luaurc, encoding="utf-8") as handle:
            parsed = json.loads(_strip_jsonc_comments(handle.read()))
        raw = parsed.get("aliases") if isinstance(parsed, dict) else None
        if isinstance(raw, dict):
            aliases = {
                str(key).lstrip("@"): str(value)
                for key, value in raw.items()
                if isinstance(value, str)
            }
    except (OSError, ValueError, UnicodeDecodeError):
        aliases = {}

    _LUAU_ALIAS_CACHE[normalized] = aliases
    return aliases


def _luau_module_index(scan_path: str) -> dict[str, list[str]]:
    """Index every module-path suffix under *scan_path* to its source files.

    src/Shared/Common/Physics.luau registers under "physics", "common/physics",
    "shared/common/physics" and so on, so an alias tail can be matched at
    whatever depth a build manifest happens to mount it. Keys are lowercased
    because Roblox instance names are matched case-insensitively by most
    tooling; the stored paths stay exact.
    """
    normalized = os.path.normpath(scan_path)
    cached = _LUAU_MODULE_INDEX_CACHE.get(normalized)
    if cached is not None:
        return cached

    index: dict[str, list[str]] = {}
    for dirpath, dirnames, filenames in os.walk(normalized):
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for filename in filenames:
            if not filename.endswith(_LUAU_EXTENSIONS):
                continue
            abs_path = os.path.join(dirpath, filename)
            rel = os.path.relpath(abs_path, normalized).replace(os.sep, "/")
            module_path = _strip_luau_extension(rel)
            # An init module is addressed by its directory, never by "init".
            if module_path.rsplit("/", 1)[-1] == "init":
                module_path = module_path.rpartition("/")[0]
            if not module_path:
                continue
            segments = module_path.lower().split("/")
            for start in range(len(segments)):
                index.setdefault("/".join(segments[start:]), []).append(abs_path)

    _LUAU_MODULE_INDEX_CACHE[normalized] = index
    return index


def _shared_prefix_length(left: str, right: str) -> int:
    """Count leading path segments two absolute paths have in common."""
    left_parts = os.path.normcase(left).split(os.sep)
    right_parts = os.path.normcase(right).split(os.sep)
    shared = 0
    for a, b in zip(left_parts, right_parts):
        if a != b:
            break
        shared += 1
    return shared


def _resolve_luau_alias_tail(
    segments: list[str], scan_path: str, source_file: str
) -> str | None:
    """Match an alias path against the module index, longest tail first."""
    if not segments:
        return None
    index = _luau_module_index(scan_path)
    for start in range(len(segments)):
        matches = index.get("/".join(seg.lower() for seg in segments[start:]))
        if not matches:
            continue
        if len(matches) == 1:
            return matches[0]
        # Several files answer to the same tail — a duplicated tree, a vendored
        # copy, one app per directory in a monorepo. Prefer the copy nearest
        # the requiring file, and give up when even that is tied rather than
        # inventing an edge. A shorter tail would only be less specific, so
        # stop here instead of widening the search.
        ranked = sorted(
            matches,
            key=lambda candidate: _shared_prefix_length(candidate, source_file),
            reverse=True,
        )
        best = _shared_prefix_length(ranked[0], source_file)
        runner_up = _shared_prefix_length(ranked[1], source_file)
        return ranked[0] if best > runner_up else None
    return None


def _luau_relative_bases(source_file: str, source_dir: str) -> list[str]:
    """Return the directories a relative require may be resolved against.

    Runtimes disagree on what "./" means inside an init file: some treat the
    init module as the file it is, others as the directory it initialises, so
    the same require lands one level apart. Both bases are tried, and only an
    existing file is ever accepted, so the ambiguity costs a stat rather than a
    wrong edge.
    """
    if os.path.splitext(os.path.basename(source_file))[0] != "init":
        return [source_dir]
    return [source_dir, os.path.dirname(source_dir)]


def resolve_luau_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve a Luau require path string to a local file."""
    if not import_text:
        return None

    text = import_text.strip()
    source_dir = os.path.dirname(source_file)

    if text.startswith(("./", "../")):
        for base in _luau_relative_bases(source_file, source_dir):
            resolved = _luau_module_file(os.path.normpath(os.path.join(base, text)))
            if resolved:
                return resolved
        return None

    if text.startswith("@"):
        alias, _, remainder = text[1:].partition("/")
        if not alias:
            return None
        tail = [seg for seg in remainder.split("/") if seg]

        alias_target = _read_luaurc_aliases(scan_path).get(alias)
        if alias_target is not None:
            base = (
                alias_target
                if os.path.isabs(alias_target)
                else os.path.normpath(os.path.join(scan_path, alias_target))
            )
            resolved = _luau_module_file(os.path.join(base, *tail) if tail else base)
            if resolved:
                return resolved

        # "@self" addresses the requiring module's own directory. For an init
        # file that is the directory it initialises, which is also its parent,
        # so dirname() is correct either way.
        if alias == "self":
            return _luau_module_file(os.path.join(source_dir, *tail)) if tail else None

        return _resolve_luau_alias_tail(tail, scan_path, source_file)

    segments = [seg for seg in text.split("/") if seg]
    if not segments:
        return None

    if len(segments) > 1:
        return _luau_module_file(
            os.path.join(scan_path, *segments)
        ) or _resolve_luau_alias_tail(segments, scan_path, source_file)

    # Bare name: a sibling module first, then anything uniquely named below root.
    return _luau_module_file(
        os.path.join(source_dir, segments[0])
    ) or _resolve_luau_alias_tail(segments, scan_path, source_file)
