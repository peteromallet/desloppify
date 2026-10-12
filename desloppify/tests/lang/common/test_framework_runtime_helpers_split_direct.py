"""Direct tests for shared framework runtime helper split modules."""

from __future__ import annotations

from types import SimpleNamespace

import desloppify.languages._framework.base.lang_config_runtime as runtime_mod
import desloppify.languages._framework.base.shared_phases_helpers as shared_helpers_mod
from desloppify.languages._framework.base.types_shared import DetectorCoverageStatus


class _ZoneMap:
    def __init__(self, allowed_files: set[str]):
        self._allowed_files = allowed_files

    def all_files(self):
        return list(self._allowed_files)

    def get(self, file_path: str):
        if file_path in self._allowed_files:
            return "production"
        return "test"


def test_in_scope_tests_with_other_extensions_are_discovered(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "model.test.mjs").write_text("import '../src/model.ts';")
    (tests / "model.test.ts").write_text("import '../src/model.ts';")
    lang = SimpleNamespace(
        external_test_dirs=["tests"],
        test_file_extensions=[".ts", ".mjs"],
        extensions=[".ts"],
    )
    found = shared_helpers_mod._find_external_test_files(
        tmp_path, lang, get_project_root_fn=lambda: tmp_path,
    )
    assert found == {str(tests / "model.test.mjs")}


def test_runtime_config_value_helpers() -> None:
    assert runtime_mod._is_numeric(1) is True
    assert runtime_mod._is_numeric(True) is False

    assert runtime_mod.coerce_value("true", bool, False) is True
    assert runtime_mod.coerce_value("0", bool, True) is False
    assert runtime_mod.coerce_value("12", int, 0) == 12
    assert runtime_mod.coerce_value("3.5", float, 0.0) == 3.5
    assert runtime_mod.coerce_value(123, str, "") == "123"

    specs = {
        "enabled": SimpleNamespace(type=bool, default=False),
        "limit": SimpleNamespace(type=int, default=5),
    }
    normalized = runtime_mod.normalize_spec_values({"enabled": "yes", "limit": "10"}, specs)
    assert normalized == {"enabled": True, "limit": 10}

    defaults = {"enabled": True}
    assert runtime_mod.runtime_value(defaults, specs, "enabled", default=False) is True
    assert runtime_mod.runtime_value(defaults, specs, "limit", default=0) == 5


def test_shared_phase_helpers_cover_filtering_and_coverage_recording(monkeypatch, tmp_path) -> None:
    zone_map = _ZoneMap({"src/a.py", "src/b.py"})
    entries = [
        {
            "locations": [
                {"file": "src/a.py", "line": 1},
                {"file": "src/b.py", "line": 2},
                {"file": "tests/a_test.py", "line": 3},
            ]
        }
    ]
    filtered = shared_helpers_mod._filter_boilerplate_entries_by_zone(entries, zone_map)
    assert len(filtered) == 1
    assert filtered[0]["distinct_files"] == 2

    project_root = tmp_path
    (project_root / "tests").mkdir(parents=True, exist_ok=True)
    (project_root / "tests" / "sample_test.py").write_text("print('ok')\n", encoding="utf-8")
    lang = SimpleNamespace(
        external_test_dirs=["tests"],
        test_file_extensions=[".py"],
        extensions=[".py"],
    )
    external_tests = shared_helpers_mod._find_external_test_files(
        path=project_root / "src",
        lang=lang,
        get_project_root_fn=lambda: project_root,
    )
    assert any(path.endswith("sample_test.py") for path in external_tests)

    issues = shared_helpers_mod._entries_to_issues(
        "unused",
        [
            {
                "file": "src/a.py",
                "tier": 2,
                "confidence": "medium",
                "summary": "unused value",
                "name": "value",
            }
        ],
    )
    assert len(issues) == 1
    assert issues[0]["detector"] == "unused"

    logs: list[str] = []
    shared_helpers_mod._log_phase_summary("unused", issues, 1, "symbols", log_fn=logs.append)
    assert logs and "unused" in logs[0]

    full = DetectorCoverageStatus(detector="unused", status="full", confidence=0.9, summary="ok")
    reduced = DetectorCoverageStatus(detector="unused", status="reduced", confidence=0.5, summary="partial")

    full_dict = shared_helpers_mod._coverage_to_dict(full)
    reduced_dict = shared_helpers_mod._coverage_to_dict(reduced)
    merged = shared_helpers_mod._merge_detector_coverage(full_dict, reduced_dict)
    assert merged["status"] == "reduced"
    assert merged["confidence"] == 0.5

    lang_runtime = SimpleNamespace(detector_coverage={})
    shared_helpers_mod._record_detector_coverage(lang_runtime, full)
    shared_helpers_mod._record_detector_coverage(lang_runtime, reduced)
    assert lang_runtime.detector_coverage["unused"]["status"] == "reduced"
