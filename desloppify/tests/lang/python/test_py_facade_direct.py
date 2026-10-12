"""Direct tests for Python facade detection."""

from __future__ import annotations

from pathlib import Path

from desloppify.languages.python.detectors.facade import is_py_facade


def _detect(tmp_path: Path, source: str) -> dict | None:
    path = tmp_path / "__init__.py"
    path.write_text(source)
    return is_py_facade(str(path))


def test_future_import_only_package_marker_is_not_a_facade(tmp_path: Path):
    result = _detect(
        tmp_path,
        '"""Package marker."""\nfrom __future__ import annotations\n',
    )

    assert result is None


def test_future_import_does_not_hide_real_reexport(tmp_path: Path):
    result = _detect(
        tmp_path,
        (
            '"""Public package surface."""\n'
            "from __future__ import annotations\n"
            "from package.api import PublicName\n"
        ),
    )

    assert result == {"imports_from": ["package.api"], "loc": 3}
