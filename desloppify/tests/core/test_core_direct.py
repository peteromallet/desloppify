"""Direct tests for core helper modules with prior transitive-only coverage."""

from __future__ import annotations

import json
import logging

import desloppify.core.fallbacks as fallbacks_mod
import desloppify.core.query as query_mod


def test_write_query_injects_config_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(query_mod, "load_config", lambda: {"target_strict_score": 97})
    monkeypatch.setattr(
        query_mod,
        "config_for_query",
        lambda cfg: {"target_strict_score": cfg["target_strict_score"]},
    )
    query_path = tmp_path / "query.json"
    payload = {"command": "status"}

    query_mod.write_query(payload, query_file=query_path)

    saved = json.loads(query_path.read_text())
    assert saved["command"] == "status"
    assert saved["config"]["target_strict_score"] == 97


def test_write_query_records_config_error(tmp_path, monkeypatch):
    def _raise_config_error():
        raise ValueError("invalid config")

    monkeypatch.setattr(query_mod, "load_config", _raise_config_error)
    query_path = tmp_path / "query.json"
    payload = {"command": "scan"}

    query_mod.write_query(payload, query_file=query_path)

    saved = json.loads(query_path.read_text())
    assert saved["command"] == "scan"
    assert "config_error" in saved
    assert "invalid config" in saved["config_error"]


def test_restore_files_best_effort_collects_failures():
    snapshots = {"a.txt": "A", "b.txt": "B"}
    restored: list[tuple[str, str]] = []

    def _write(path: str, content: str) -> None:
        if path == "b.txt":
            raise OSError("disk full")
        restored.append((path, content))

    failed = fallbacks_mod.restore_files_best_effort(snapshots, _write)
    assert restored == [("a.txt", "A")]
    assert failed == ["b.txt"]


def test_log_best_effort_failure_debugs(caplog):
    logger = logging.getLogger("desloppify.tests.core_direct")

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        fallbacks_mod.log_best_effort_failure(
            logger, "read cache", OSError("no access")
        )

    assert "Best-effort fallback failed while trying to read cache" in caplog.text
