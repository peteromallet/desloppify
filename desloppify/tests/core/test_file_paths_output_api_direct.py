"""Direct tests for core.file_paths and core.output_api wrappers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import desloppify.core.file_paths as file_paths_mod
import desloppify.core.output_api as output_api_mod


def test_file_path_helpers_match_and_normalize() -> None:
    assert file_paths_mod.matches_exclusion("pkg/tests/test_a.py", "tests")
    assert file_paths_mod.matches_exclusion("pkg/mod/file.py", "pkg/mod")
    assert file_paths_mod.matches_exclusion("pkg/mod/file.py", "m*")
    assert file_paths_mod.normalize_path_separators(r"pkg\mod\file.py") == "pkg/mod/file.py"


def test_resolve_scan_file_prefers_scan_root_and_safe_write_text(tmp_path: Path) -> None:
    scan_root = tmp_path / "scan"
    scan_root.mkdir()
    target = scan_root / "example.py"
    target.write_text("print('ok')\n")

    resolved = file_paths_mod.resolve_scan_file("example.py", scan_root=scan_root)
    assert resolved == target.resolve()
    assert file_paths_mod.resolve_path(str(target)) == str(target.resolve())

    write_target = tmp_path / "out" / "value.txt"
    file_paths_mod.safe_write_text(write_target, "hello")
    assert write_target.read_text() == "hello"


def test_output_api_display_helpers(capsys) -> None:
    colored = output_api_mod.colorize("hello", "green")
    assert "hello" in colored

    output_api_mod.log("status-line")
    assert "status-line" in capsys.readouterr().err

    output_api_mod.print_table(["A"], [["1"]])
    table_output = capsys.readouterr().out
    assert "A" in table_output
    assert "1" in table_output

    args = SimpleNamespace(json=False, top=5)
    rendered = output_api_mod.display_entries(
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
