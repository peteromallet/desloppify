"""Tests for C# function/class extractors."""

from pathlib import Path

import pytest

import desloppify.core._internal.text_utils as utils_text_mod
import desloppify.file_discovery as file_discovery_mod
import desloppify.utils as utils_mod
from desloppify.languages.csharp.extractors import (
    extract_csharp_classes,
    extract_csharp_functions,
    find_csharp_files,
)


@pytest.fixture
def patch_project_root(monkeypatch):
    """Patch PROJECT_ROOT across all modules that define/import it."""
    def _patch(tmp_path):
        monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(utils_text_mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(file_discovery_mod, "PROJECT_ROOT", tmp_path)
        utils_mod._find_source_files_cached.cache_clear()
    return _patch


def test_extract_csharp_functions_block_and_expression(tmp_path):
    f = tmp_path / "Calc.cs"
    f.write_text(
        """
namespace Sample;
public class Calc {
    public int Add(int a, int b) {
        var c = a + b;
        return c;
    }
    public int Double(int x) => x * 2;
}
"""
    )
    funcs = extract_csharp_functions(str(f))
    names = {fn.name for fn in funcs}
    assert "Add" in names
    assert "Double" in names
    add = next(fn for fn in funcs if fn.name == "Add")
    assert add.params == ["a", "b"]


def test_extract_csharp_classes_with_methods(tmp_path, patch_project_root):
    root = tmp_path
    src = root / "Models"
    src.mkdir(parents=True)
    f = src / "OrderService.cs"
    f.write_text(
        """
namespace Sample.Services;
public class OrderService : BaseService, IOrderService {
    private readonly int _x;
    public int Count { get; set; }
    public void A() { }
    public void B() { }
}
"""
    )
    patch_project_root(root)
    classes = extract_csharp_classes(root)
    assert len(classes) >= 1
    cls = next(c for c in classes if c.name == "OrderService")
    assert "BaseService" in cls.base_classes
    assert "Count" in cls.attributes
    assert len(cls.methods) >= 2


def test_find_csharp_files_excludes_build_dirs(tmp_path, patch_project_root):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Main.cs").write_text("class MainClass {}")
    (tmp_path / "obj").mkdir()
    (tmp_path / "obj" / "Generated.cs").write_text("class Generated {}")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "Compiled.cs").write_text("class Compiled {}")
    patch_project_root(tmp_path)
    files = find_csharp_files(Path(tmp_path))
    assert files == ["src/Main.cs"]
