"""Direct tests for language-specific review/move helper modules."""

from __future__ import annotations

import os

import desloppify.languages.csharp.move as csharp_move_mod
import desloppify.languages.csharp.review as csharp_review_mod
import desloppify.languages.typescript.review as ts_review_mod


def test_csharp_module_patterns_and_api_surface():
    content = """
namespace App.Core;
public class Service {
    public void Run() {}
    public async Task<int> RunAsync() => 1;
}
"""
    patterns = csharp_review_mod.module_patterns(content)
    assert "namespace" in patterns
    assert "public_types" in patterns
    assert "public_methods" in patterns

    file_contents = {os.path.abspath("Service.cs"): content}
    surface = csharp_review_mod.api_surface(file_contents)
    assert "sync_async_mix" in surface
    assert len(surface["sync_async_mix"]) == 1


def test_typescript_module_patterns_and_api_surface():
    content = """
export function run() { return 1; }
export async function runAsync() { return 2; }
export default function Entry() { return null; }
"""
    patterns = ts_review_mod.module_patterns(content)
    assert "default_export" in patterns
    assert "named_export" in patterns

    file_contents = {os.path.abspath("feature.ts"): content}
    surface = ts_review_mod.api_surface(file_contents)
    assert "sync_async_mix" in surface
    assert len(surface["sync_async_mix"]) == 1


def test_csharp_move_placeholder_behaviors():
    graph = {"a.cs": {"imports": set()}}
    replacements = [("A", "B")]
    self_changes = [("C", "D")]
    moving_files = {"x.cs"}

    assert csharp_move_mod.find_replacements("a.cs", "b.cs", graph) == {}
    assert csharp_move_mod.find_self_replacements("a.cs", "b.cs", graph) == []
    assert (
        csharp_move_mod.filter_intra_package_importer_changes(
            "a.cs", replacements, moving_files
        )
        == replacements
    )
    assert (
        csharp_move_mod.filter_directory_self_changes(
            "a.cs", self_changes, moving_files
        )
        == self_changes
    )
