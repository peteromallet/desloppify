"""Tests for implicit mixin self-contract coupling detection."""

from pathlib import Path

from desloppify.languages.python.detectors.coupling_contracts import (
    detect_implicit_mixin_contracts,
)


def _write(tmp_path: Path, rel: str, content: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_detects_implicit_mixin_contract_dependencies(tmp_path):
    _write(
        tmp_path,
        "control/phases/worker_capacity.py",
        (
            "class WorkerCapacityMixin:\n"
            "    def scale(self):\n"
            "        return self.db + self.runpod + self.config + self.last_scale_down_at\n"
        ),
    )
    entries, candidates = detect_implicit_mixin_contracts(tmp_path)
    assert candidates == 1
    assert len(entries) == 1
    assert entries[0]["class"] == "WorkerCapacityMixin"
    assert entries[0]["required_count"] == 4
    assert "db" in entries[0]["required_attrs"]


def test_ignores_mixin_with_declared_contract_or_writes(tmp_path):
    _write(
        tmp_path,
        "control/phases/state.py",
        (
            "class StateMixin:\n"
            "    db: object\n"
            "    config: dict\n"
            "    def __init__(self):\n"
            "        self.runpod = object()\n"
            "    def act(self):\n"
            "        return self.db, self.config, self.runpod\n"
        ),
    )
    entries, _ = detect_implicit_mixin_contracts(tmp_path)
    assert entries == []


def test_ignores_protocol_backed_contract(tmp_path):
    _write(
        tmp_path,
        "control/phases/lifecycle.py",
        (
            "class HostProtocol: ...\n"
            "class LifecycleMixin(HostProtocol):\n"
            "    def tick(self):\n"
            "        return self.db, self.config, self.runpod\n"
        ),
    )
    entries, _ = detect_implicit_mixin_contracts(tmp_path)
    assert entries == []


def test_ignores_mixin_calling_own_class_body_methods(tmp_path):
    _write(
        tmp_path,
        "control/phases/merge.py",
        (
            "class ChunkMergeMixin:\n"
            "    db: object\n"
            "    def create_staging_table(self): ...\n"
            "    def get_chunk_files(self): ...\n"
            "    def _is_valid_chunk(self, chunk): ...\n"
            "    def _process_chunk(self, chunk): ...\n"
            "    def merge(self):\n"
            "        self.create_staging_table()\n"
            "        self.get_chunk_files()\n"
            "        self._is_valid_chunk(None)\n"
            "        self._process_chunk(None)\n"
            "        return self.db\n"
        ),
    )
    entries, candidates = detect_implicit_mixin_contracts(tmp_path)
    assert candidates == 1
    assert entries == []


def test_flags_host_provided_attrs_not_defined_in_mixin(tmp_path):
    _write(
        tmp_path,
        "control/phases/batch.py",
        (
            "class Host:\n"
            "    db: object\n"
            "    config: dict\n"
            "    session: object\n"
            "class BatchMixin:\n"
            "    def run(self):\n"
            "        return self.db + self.config + self.session\n"
        ),
    )
    entries, _ = detect_implicit_mixin_contracts(tmp_path)
    assert len(entries) == 1
    assert entries[0]["class"] == "BatchMixin"
    assert entries[0]["required_count"] == 3
    assert set(entries[0]["required_attrs"]) == {"db", "config", "session"}

