"""Shared helpers for Python smell detector tests."""

import textwrap
from pathlib import Path

import pytest


@pytest.fixture()
def write_py(tmp_path: Path):
    """Fixture that returns a helper to write a Python file and get the directory."""

    def _write(code: str, filename: str = "test_mod.py") -> Path:
        f = tmp_path / filename
        f.write_text(textwrap.dedent(code))
        return tmp_path

    return _write


def smell_ids(entries: list[dict]) -> set[str]:
    """Extract the set of smell IDs from detect_smells output."""
    return {e["id"] for e in entries}


def find_smell(entries: list[dict], smell_id: str) -> dict | None:
    """Find a specific smell entry by ID."""
    for e in entries:
        if e["id"] == smell_id:
            return e
    return None
