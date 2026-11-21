"""Relative scan roots must produce exclusions usable by external tools."""

from pathlib import Path

from desloppify.base.discovery.source import collect_exclude_dirs


def test_relative_scan_root_exclusions_are_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = collect_exclude_dirs(Path("."), extra_exclusions=("outputs",))
    assert str(tmp_path / "outputs") in result
    assert all(Path(path).is_absolute() for path in result)


def test_nested_relative_root_resolves_against_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = collect_exclude_dirs(Path("project"), extra_exclusions=("vendor",))
    assert str(tmp_path / "project" / "vendor") in result
