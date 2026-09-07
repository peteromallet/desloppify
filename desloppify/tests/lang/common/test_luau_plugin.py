"""Tests for the Luau language plugin and its require-by-string resolver."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from desloppify.languages._framework.treesitter.imports.resolvers_scripts import (
    reset_luau_import_caches,
    resolve_luau_import,
)


@pytest.fixture(autouse=True)
def _clear_luau_caches():
    reset_luau_import_caches()
    yield
    reset_luau_import_caches()


def _write(path: Path, text: str = "return {}\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A small Roblox-shaped tree: src/ sources plus a vendored Packages dir."""
    _write(tmp_path / "src" / "Shared" / "Tools" / "GameClock.luau")
    _write(tmp_path / "src" / "Shared" / "Common" / "Combat" / "init.luau")
    _write(tmp_path / "src" / "Server" / "Services" / "DataService" / "Types.luau")
    _write(tmp_path / "src" / "Server" / "Services" / "DataService" / "init.luau")
    _write(
        tmp_path / "src" / "Server" / "Services" / "DataService" / "DataHandler.luau"
    )
    _write(tmp_path / "Packages" / "Knit.lua")
    return tmp_path


def test_relative_require_resolves_against_source_dir(project: Path):
    source = str(project / "src/Server/Services/DataService/DataHandler.luau")
    assert resolve_luau_import("./Types", source, str(project)) == str(
        project / "src/Server/Services/DataService/Types.luau"
    )


def test_parent_relative_require_resolves(project: Path):
    _write(project / "src" / "Server" / "Services" / "Shared.luau")
    source = str(project / "src/Server/Services/DataService/DataHandler.luau")
    assert resolve_luau_import("../Shared", source, str(project)) == str(
        project / "src/Server/Services/Shared.luau"
    )


def test_directory_require_resolves_to_init_module(project: Path):
    source = str(project / "src/Server/Services/DataService/DataHandler.luau")
    assert resolve_luau_import(
        "@game/ReplicatedStorage/Common/Combat", source, str(project)
    ) == str(project / "src/Shared/Common/Combat/init.luau")


def test_init_file_relative_require_accepts_either_interpretation(project: Path):
    """Runtimes disagree on the base directory for a relative require in init."""
    source = str(project / "src/Server/Services/DataService/init.luau")
    # Resolves as if init were the file it is (sibling Types.luau).
    assert resolve_luau_import("./Types", source, str(project)) == str(
        project / "src/Server/Services/DataService/Types.luau"
    )
    # And as if init stood for its own directory (one level up).
    _write(project / "src" / "Server" / "Services" / "Registry.luau")
    assert resolve_luau_import("./Registry", source, str(project)) == str(
        project / "src/Server/Services/Registry.luau"
    )


def test_self_alias_resolves_to_own_directory(project: Path):
    source = str(project / "src/Server/Services/DataService/init.luau")
    assert resolve_luau_import("@self/Types", source, str(project)) == str(
        project / "src/Server/Services/DataService/Types.luau"
    )


def test_self_alias_without_remainder_is_unresolved(project: Path):
    source = str(project / "src/Server/Services/DataService/init.luau")
    assert resolve_luau_import("@self", source, str(project)) is None


def test_luaurc_alias_is_honoured(project: Path):
    (project / ".luaurc").write_text(
        json.dumps({"aliases": {"shared": "./src/Shared"}}), encoding="utf-8"
    )
    source = str(project / "src/Server/Services/DataService/DataHandler.luau")
    assert resolve_luau_import("@shared/Tools/GameClock", source, str(project)) == str(
        project / "src/Shared/Tools/GameClock.luau"
    )


def test_luaurc_with_line_comments_still_parses(project: Path):
    (project / ".luaurc").write_text(
        '{\n  // the shared tree\n  "aliases": { "shared": "./src/Shared" }\n}\n',
        encoding="utf-8",
    )
    source = str(project / "src/Server/Services/DataService/DataHandler.luau")
    assert resolve_luau_import("@shared/Tools/GameClock", source, str(project)) == str(
        project / "src/Shared/Tools/GameClock.luau"
    )


def test_malformed_luaurc_does_not_raise(project: Path):
    (project / ".luaurc").write_text("{ not json", encoding="utf-8")
    source = str(project / "src/Server/Services/DataService/DataHandler.luau")
    assert resolve_luau_import("@shared/Nope", source, str(project)) is None


def test_host_alias_tail_matches_module_index(project: Path):
    """A Roblox "@game" path maps through the instance tree, not the filesystem."""
    source = str(project / "src/Server/Services/DataService/DataHandler.luau")
    assert resolve_luau_import(
        "@game/ReplicatedStorage/Tools/GameClock", source, str(project)
    ) == str(project / "src/Shared/Tools/GameClock.luau")


def test_ambiguous_alias_tail_is_not_guessed(project: Path):
    _write(project / "src" / "Client" / "Tools" / "GameClock.luau")
    source = str(project / "src/Server/Services/DataService/DataHandler.luau")
    assert (
        resolve_luau_import(
            "@game/ReplicatedStorage/Tools/GameClock", source, str(project)
        )
        is None
    )


def test_unknown_module_is_unresolved(project: Path):
    source = str(project / "src/Server/Services/DataService/DataHandler.luau")
    assert resolve_luau_import("@game/Nope/Missing", source, str(project)) is None
    assert resolve_luau_import("", source, str(project)) is None
    assert resolve_luau_import("@", source, str(project)) is None


def test_module_index_cache_is_scoped_to_scan_path(project: Path):
    source = str(project / "src/Server/Services/DataService/DataHandler.luau")
    assert resolve_luau_import("@game/Tools/GameClock", source, str(project))

    _write(project / "src" / "Client" / "Tools" / "GameClock.luau")
    # Still cached, so the new duplicate is invisible until the cache is reset.
    assert resolve_luau_import("@game/Tools/GameClock", source, str(project))

    reset_luau_import_caches(str(project))
    assert resolve_luau_import("@game/Tools/GameClock", source, str(project)) is None


def test_luau_plugin_is_registered_with_its_own_grammar():
    # Read through the registry rather than forcing a reload: a force_reload
    # here would clear registrations other tests in the session rely on.
    from desloppify.languages import available_langs, get_lang

    assert "luau" in available_langs()
    cfg = get_lang("luau")
    assert cfg.extensions == [".luau"]
    assert cfg.build_dep_graph is not None


def test_luau_spec_extracts_typed_declarations(tmp_path: Path):
    """The Lua grammar chokes on Luau types; the Luau grammar must not."""
    pytest.importorskip("tree_sitter_language_pack")
    from desloppify.languages._framework.treesitter import LUAU_SPEC
    from desloppify.languages._framework.treesitter.analysis.extractors import (
        ts_extract_functions,
    )

    module = _write(
        tmp_path / "Handler.luau",
        "export type Singleton = { doThing: (Player) -> () }\n"
        "local Handler = {}\n"
        "function Handler.doThing(player: Player): boolean\n"
        "\tlocal count: number = 1\n"
        "\treturn count > 0\n"
        "end\n"
        "function Handler:Method(a: string)\n"
        "\treturn a\n"
        "end\n"
        "return Handler\n",
    )

    names = {
        fn.name for fn in ts_extract_functions(tmp_path, LUAU_SPEC, [str(module)])
    }
    assert names == {"Handler.doThing", "Handler:Method"}


def _unused(tmp_path: Path, name: str, body: str) -> list[str]:
    from desloppify.languages._framework.treesitter import LUAU_SPEC
    from desloppify.languages._framework.treesitter.analysis.unused_imports import (
        detect_unused_imports,
    )

    pytest.importorskip("tree_sitter_language_pack")
    module = _write(tmp_path / name, body)
    return [entry["name"] for entry in detect_unused_imports([str(module)], LUAU_SPEC)]


def test_unused_import_reports_the_binding_not_the_module_path(tmp_path: Path):
    """local TeamClass = require(".../Team") binds TeamClass, not Team."""
    assert _unused(
        tmp_path,
        "Aliased.luau",
        'local TeamClass = require("@game/ReplicatedStorage/Tools/Team")\nreturn {}\n',
    ) == ["TeamClass"]


def test_used_alias_is_not_reported(tmp_path: Path):
    assert (
        _unused(
            tmp_path,
            "Used.luau",
            'local TeamClass = require("@game/ReplicatedStorage/Tools/Team")\n'
            "return TeamClass.new()\n",
        )
        == []
    )


def test_require_bound_to_no_name_is_not_reported(tmp_path: Path):
    """An inline require in a table literal binds nothing, so it cannot be unused."""
    assert (
        _unused(
            tmp_path,
            "Inline.luau",
            'local MODULES = {\n\trequire("@self/Entities/awp"),\n}\nreturn MODULES\n',
        )
        == []
    )


def test_underscore_prefixed_binding_is_not_reported(tmp_path: Path):
    """A leading underscore marks a binding deliberately left unreferenced."""
    assert (
        _unused(
            tmp_path,
            "Underscore.luau",
            'local _Types = require("@game/ReplicatedStorage/Configuration/ConchTypes")\n'
            "return {}\n",
        )
        == []
    )


def test_multiple_assignment_pairs_bindings_with_values(tmp_path: Path):
    """Targets and values line up by position, so each require checks its own name."""
    assert _unused(
        tmp_path,
        "Multi.luau",
        'local Used, Dropped = require("@game/A"), require("@game/B")\nreturn Used\n',
    ) == ["Dropped"]
