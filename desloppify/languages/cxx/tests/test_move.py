from __future__ import annotations

from desloppify.languages.cxx import move as cxx_move


def test_cxx_move_helpers_expose_scaffold_contract():
    assert isinstance(cxx_move.get_verify_hint(), str)
    assert cxx_move.get_verify_hint() == "desloppify --lang cxx detect deps"
    assert cxx_move.find_replacements("a.cpp", "b.cpp", {}) == {}
    assert cxx_move.find_self_replacements("a.cpp", "b.cpp", {}) == []
    assert cxx_move.filter_intra_package_importer_changes(
        "a.cpp", [("a", "b")], set()
    ) == [("a", "b")]
    assert cxx_move.filter_directory_self_changes(
        "a.cpp", [("a", "b")], set()
    ) == [("a", "b")]
