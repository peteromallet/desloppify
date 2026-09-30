"""External test discovery shares scan exclusions and reports honest units."""

from types import SimpleNamespace

import pytest

from desloppify.base.runtime_state import RuntimeContext, runtime_scope
from desloppify.engine.policy.zones import FileZoneMap
from desloppify.languages._framework.base.shared_phases_helpers import (
    _find_external_test_files,
)
from desloppify.languages._framework.base.shared_phases_review import (
    phase_test_coverage,
)
from desloppify.languages.python._zones import PY_ZONE_RULES


def write(root, relative, content="pass\n"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def language(**changes):
    return SimpleNamespace(
        external_test_dirs=["tests"],
        test_file_extensions=[".py"],
        extensions=[".py"],
        **changes,
    )


@pytest.mark.parametrize(
    "excluded", ["tests/legacy", "tests/skipped_test.py", "tests/**/old_*.py"]
)
def test_external_tests_respect_directory_file_and_glob_exclusions(tmp_path, excluded):
    kept = write(tmp_path, "tests/kept_test.py")
    write(tmp_path, "tests/legacy/old_test.py")
    write(tmp_path, "tests/skipped_test.py")
    with runtime_scope(RuntimeContext(project_root=tmp_path, exclusions=(excluded,))):
        tests = _find_external_test_files(tmp_path / "src", language())
    assert str(kept) in tests
    if "skipped_test" in excluded:
        assert str(tmp_path / "tests/skipped_test.py") not in tests
    else:
        assert str(tmp_path / "tests/legacy/old_test.py") not in tests


@pytest.mark.parametrize("directory", ["node_modules", "__pycache__", ".venv-tests"])
def test_external_tests_prune_default_and_virtualenv_directories(tmp_path, directory):
    kept = write(tmp_path, "tests/kept_test.py")
    hidden = write(tmp_path, f"tests/{directory}/hidden_test.py")
    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        assert _find_external_test_files(tmp_path / "src", language()) == {str(kept)}
    assert hidden.exists()


def test_injected_project_root_and_extensions_are_preserved(tmp_path):
    project = tmp_path / "project"
    kept = write(project, "tests/kept_test.js")
    write(project, "tests/ignored_test.py")
    lang = SimpleNamespace(
        external_test_dirs=["tests"], test_file_extensions=[".js"], extensions=[".py"]
    )
    with runtime_scope(RuntimeContext(project_root=tmp_path / "different")):
        assert _find_external_test_files(
            project / "src", lang, get_project_root_fn=lambda: project
        ) == {str(kept)}


def test_tests_inside_scan_root_are_not_discovered_twice(tmp_path):
    write(tmp_path, "tests/kept_test.py")
    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        assert _find_external_test_files(tmp_path, language()) == set()


def test_coverage_summary_labels_weighted_potential_not_file_count(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    write(
        tmp_path,
        "src/owner.py",
        "def owner():\n" + "    value = 1\n" * 98 + "    return value\n",
    )
    lang = language(
        zone_map=FileZoneMap(["src/owner.py"], PY_ZONE_RULES),
        dep_graph={"src/owner.py": {"imports": set(), "importer_count": 0}},
        name="python",
        complexity_map={},
    )
    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        issues, potential = phase_test_coverage(tmp_path / "src", lang)
    assert len(issues) == 1
    assert potential == {"test_coverage": 10}
    captured = capsys.readouterr()
    output = captured.err + captured.out
    assert "10 weighted coverage units" in output
    assert "10 production files" not in output
