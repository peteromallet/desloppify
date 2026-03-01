"""Direct tests for canonical core API surfaces and legacy wrappers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import desloppify.core.discovery.api as discovery_api_mod
import desloppify.core.io.api as io_api_mod
import desloppify.core.paths_api as paths_api_mod
from desloppify.core._internal.path_proxy import DynamicPathProxy


def test_discovery_api_file_search_and_cache_roundtrip(tmp_path: Path) -> None:
    prior_exclusions = discovery_api_mod.get_exclusions()
    prior_cache_enabled = discovery_api_mod.is_file_cache_enabled()

    try:
        discovery_api_mod.set_exclusions([])
        discovery_api_mod.disable_file_cache()
        assert discovery_api_mod.is_file_cache_enabled() is False
        with discovery_api_mod.file_cache_scope():
            assert discovery_api_mod.is_file_cache_enabled() is True
        assert discovery_api_mod.is_file_cache_enabled() is False
        discovery_api_mod.enable_file_cache()
        assert discovery_api_mod.is_file_cache_enabled() is True

        py_file = tmp_path / "module.py"
        txt_file = tmp_path / "notes.txt"
        py_file.write_text("x = 1\n")
        txt_file.write_text("skip\n")

        discovered = discovery_api_mod.find_source_files(tmp_path, [".py"])
        discovered_names = {Path(path).name for path in discovered}
        assert discovered_names == {"module.py"}
        assert discovery_api_mod.read_file_text(str(py_file)) == "x = 1\n"

        py_only = discovery_api_mod.find_py_files(tmp_path)
        assert {Path(path).name for path in py_only} == {"module.py"}
    finally:
        discovery_api_mod.set_exclusions(list(prior_exclusions))
        if prior_cache_enabled:
            discovery_api_mod.enable_file_cache()
        else:
            discovery_api_mod.disable_file_cache()
        discovery_api_mod.clear_source_file_cache_for_tests()


def test_io_api_display_helpers(capsys) -> None:
    colored = io_api_mod.colorize("hello", "green")
    assert "hello" in colored

    io_api_mod.log("io-status-line")
    assert "io-status-line" in capsys.readouterr().err

    io_api_mod.print_table(["A"], [["1"]])
    table_output = capsys.readouterr().out
    assert "A" in table_output
    assert "1" in table_output

    args = SimpleNamespace(json=False, top=5)
    rendered = io_api_mod.display_entries(
        args,
        [{"id": "x"}],
        label="Entries",
        empty_msg="none",
        columns=["ID"],
        widths=[2],
        row_fn=lambda item: [item["id"]],
    )
    list_output = capsys.readouterr().out
    assert rendered is True
    assert "Entries: 1" in list_output
    assert "x" in list_output


def test_paths_api_wrapper_routes_to_pathing_api(tmp_path: Path) -> None:
    source = tmp_path / "src" / "example.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('ok')\n")

    with pytest.warns(DeprecationWarning):
        root = paths_api_mod.get_project_root()
    assert isinstance(root, Path)

    with pytest.warns(DeprecationWarning):
        resolved = paths_api_mod.resolve_scan_file("example.py", scan_root=source.parent)
    assert resolved == source.resolve()

    output_file = tmp_path / "out" / "value.txt"
    with pytest.warns(DeprecationWarning):
        paths_api_mod.safe_write_text(output_file, "hello")
    assert output_file.read_text() == "hello"

    with pytest.warns(DeprecationWarning):
        rel_value = paths_api_mod.rel(str(source.resolve()))
    assert isinstance(rel_value, str)


def test_dynamic_path_proxy_resolves_on_each_access(tmp_path: Path) -> None:
    current = {"path": tmp_path / "one"}
    proxy = DynamicPathProxy(lambda: current["path"], label="TEST")

    assert str(proxy) == str(tmp_path / "one")
    assert proxy / "file.txt" == (tmp_path / "one" / "file.txt")
    assert "TEST(" in repr(proxy)

    current["path"] = tmp_path / "two"
    assert str(proxy) == str(tmp_path / "two")
