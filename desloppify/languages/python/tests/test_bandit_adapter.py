"""Tests for Python Bandit adapter zone filtering behavior."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from desloppify.base.discovery.file_paths import rel
from desloppify.base.discovery.paths import get_project_root
from desloppify.engine.policy.zones import COMMON_ZONE_RULES, FileZoneMap, Zone
from desloppify.languages.python.detectors import bandit_adapter as adapter_mod


@dataclass
class _StubZoneMap:
    zone: Zone

    def get(self, _path: str) -> Zone:
        return self.zone


class _RelOnlyZoneMap:
    def get(self, path: str) -> Zone:
        return Zone.TEST if path.startswith("desloppify/tests/") else Zone.PRODUCTION


def _sample_result(*, test_id: str = "B108") -> dict[str, object]:
    return {
        "filename": "desloppify/tests/test_file.py",
        "test_id": test_id,
        "issue_severity": "MEDIUM",
        "issue_confidence": "MEDIUM",
        "line_number": 10,
        "issue_text": "hardcoded temp path",
        "test_name": "hardcoded_tmp_directory",
        "code": "x = '/tmp/demo'",
        "more_info": "https://example.test",
    }


def test_to_security_entry_skips_test_zone():
    entry = adapter_mod._to_security_entry(_sample_result(), _StubZoneMap(Zone.TEST))
    assert entry is None


def test_to_security_entry_skips_config_zone():
    entry = adapter_mod._to_security_entry(_sample_result(), _StubZoneMap(Zone.CONFIG))
    assert entry is None


def test_to_security_entry_keeps_production_zone():
    entry = adapter_mod._to_security_entry(
        _sample_result(),
        _StubZoneMap(Zone.PRODUCTION),
    )
    assert isinstance(entry, dict)
    assert entry["name"] == "security::B108::desloppify/tests/test_file.py::10"


def test_to_security_entry_normalizes_absolute_paths_before_zone_lookup():
    result = _sample_result()
    result["filename"] = str(get_project_root() / "desloppify/tests/test_file.py")
    entry = adapter_mod._to_security_entry(result, _RelOnlyZoneMap())
    assert entry is None


def test_to_security_entry_skips_test_zone_with_abs_key_zone_map():
    abs_path = str(get_project_root() / "desloppify/tests/test_file.py")
    zone_map = FileZoneMap([abs_path], COMMON_ZONE_RULES, rel_fn=rel)
    result = _sample_result()
    result["filename"] = abs_path

    entry = adapter_mod._to_security_entry(result, zone_map)
    assert entry is None


def test_detect_with_bandit_uses_absolute_scan_path(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeCompleted:
        stdout = '{"results": [], "metrics": {}}'

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeCompleted()

    monkeypatch.setattr(adapter_mod.subprocess, "run", _fake_run)

    result = adapter_mod.detect_with_bandit(
        Path("."),
        zone_map=None,
        exclude_dirs=["/tmp/demo/.venv"],
    )

    assert result.status.state == "ok"
    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert Path(cmd[-1]).is_absolute()


def test_detect_with_bandit_files_batches_discovered_files_without_duplicates(monkeypatch, tmp_path):
    files = [tmp_path / f"module_{index}.py" for index in range(3)]
    calls: list[list[Path]] = []
    commands: list[list[str]] = []

    class _FakeCompleted:
        def __init__(self, targets: list[Path]) -> None:
            self.stdout = json.dumps(
                {
                    "results": [
                        {
                            "filename": str(target),
                            "test_id": "B102",
                            "issue_severity": "HIGH",
                            "issue_confidence": "HIGH",
                            "issue_text": "exec used",
                            "line_number": 1,
                            "test_name": "exec_used",
                            "code": "exec(value)",
                            "more_info": "https://example.test/B102",
                        }
                        for target in targets
                    ],
                    "metrics": {str(target): {} for target in targets},
                }
            )

    def _fake_run(cmd, **_kwargs):
        targets = [Path(value) for value in cmd if value.endswith(".py")]
        calls.append(targets)
        commands.append(cmd)
        return _FakeCompleted(targets)

    monkeypatch.setattr(adapter_mod.subprocess, "run", _fake_run)

    result = adapter_mod.detect_with_bandit_files(
        [*files, files[0]],
        zone_map=None,
        batch_size=2,
        exclude_dirs=[str(tmp_path / ".venv")],
        skip_tests=["B101"],
    )

    assert [len(targets) for targets in calls] == [2, 1]
    assert all("--exclude" in command for command in commands)
    assert all("--skip" in command for command in commands)
    assert result.status.state == "ok"
    assert result.files_scanned == 3
    assert len(result.entries) == 3


def test_detect_with_bandit_files_retains_completed_batches_on_timeout(monkeypatch, tmp_path):
    files = [tmp_path / "first.py", tmp_path / "second.py"]
    calls = 0

    class _FakeCompleted:
        stdout = json.dumps(
            {
                "results": [
                    {
                        "filename": str(files[0]),
                        "test_id": "B102",
                        "issue_severity": "HIGH",
                        "issue_confidence": "HIGH",
                        "issue_text": "exec used",
                        "line_number": 1,
                        "test_name": "exec_used",
                        "code": "exec(value)",
                        "more_info": "https://example.test/B102",
                    }
                ],
                "metrics": {str(files[0]): {}},
            }
        )

    def _fake_run(_cmd, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise subprocess.TimeoutExpired("bandit", 120)
        return _FakeCompleted()

    monkeypatch.setattr(adapter_mod.subprocess, "run", _fake_run)

    result = adapter_mod.detect_with_bandit_files(files, zone_map=None, batch_size=1)

    assert result.status.state == "timeout"
    assert result.status.detail.startswith("batch 2/2: timeout=")
    assert result.status.detail.endswith("s")
    assert result.files_scanned == 1
    assert len(result.entries) == 1


def test_detect_with_bandit_files_skips_subprocess_for_empty_input(monkeypatch):
    def _unexpected_run(*_args, **_kwargs):
        raise AssertionError("Bandit should not run for an empty source list")

    monkeypatch.setattr(adapter_mod.subprocess, "run", _unexpected_run)

    result = adapter_mod.detect_with_bandit_files([], zone_map=None)

    assert result.status.state == "ok"
    assert result.files_scanned == 0
    assert result.entries == []


def test_detect_with_bandit_files_marks_bandit_errors_as_reduced_coverage(monkeypatch, tmp_path):
    file = tmp_path / "missing.py"

    class _FakeCompleted:
        stdout = json.dumps(
            {
                "errors": [{"filename": str(file), "reason": "No such file"}],
                "metrics": {},
                "results": [],
            }
        )

    monkeypatch.setattr(adapter_mod.subprocess, "run", lambda *_args, **_kwargs: _FakeCompleted())

    result = adapter_mod.detect_with_bandit_files([file], zone_map=None)

    assert result.status.state == "error"
    assert result.status.detail == "batch 1/1: bandit reported 1 file error(s)"
    assert result.status.coverage() is not None


def test_detect_with_bandit_files_rejects_missing_target_metrics(monkeypatch, tmp_path):
    file = tmp_path / "module.py"

    class _FakeCompleted:
        stdout = json.dumps({"errors": [], "metrics": {}, "results": []})

    monkeypatch.setattr(adapter_mod.subprocess, "run", lambda *_args, **_kwargs: _FakeCompleted())

    result = adapter_mod.detect_with_bandit_files([file], zone_map=None)

    assert result.status.state == "error"
    assert result.status.detail == "batch 1/1: bandit omitted metrics for 1 target(s)"
    assert result.status.coverage() is not None


def test_detect_with_bandit_files_keeps_the_original_total_timeout(monkeypatch, tmp_path):
    files = [tmp_path / "first.py", tmp_path / "second.py"]
    observed_timeouts: list[float] = []
    ticks = iter([100.0, 100.0, 221.0])

    def _fake_run(_targets, _zone_map, *, timeout, **_kwargs):
        observed_timeouts.append(timeout)
        return adapter_mod.BanditScanResult(
            entries=[],
            files_scanned=1,
            status=adapter_mod.BanditRunStatus(state="ok"),
        )

    monkeypatch.setattr(adapter_mod, "_run_bandit", _fake_run)
    monkeypatch.setattr(adapter_mod.time, "monotonic", lambda: next(ticks))

    result = adapter_mod.detect_with_bandit_files(files, zone_map=None, batch_size=1, timeout=120)

    assert observed_timeouts == [120.0]
    assert result.files_scanned == 1
    assert result.status.state == "timeout"
    assert result.status.detail == "total timeout=120s before batch 2/2"
