"""Direct tests for C# move helpers."""

from __future__ import annotations

from desloppify.languages.csharp import move as csharp_move


def test_verify_hint_present():
    assert isinstance(csharp_move.VERIFY_HINT, str)
    assert "dotnet build" in csharp_move.VERIFY_HINT


def test_move_helpers_return_passthrough_shapes():
    replacements = csharp_move.find_replacements("a.cs", "b.cs", {})
    self_replacements = csharp_move.find_self_replacements("a.cs", "b.cs", {})
    filtered = csharp_move.filter_intra_package_importer_changes(
        "a.cs", [("a", "b")], set()
    )
    self_filtered = csharp_move.filter_directory_self_changes(
        "a.cs", [("a", "b")], set()
    )

    assert replacements == {}
    assert self_replacements == []
    assert filtered == [("a", "b")]
    assert self_filtered == [("a", "b")]
