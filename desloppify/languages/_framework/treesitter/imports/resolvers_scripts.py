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
    if not import_text or not import_text.startswith("."):
        return None

    base = os.path.dirname(source_file)
    if not os.path.isabs(base):
        base = os.path.join(scan_path, base)
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
