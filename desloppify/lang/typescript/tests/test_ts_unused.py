"""Tests for desloppify.lang.typescript.detectors.unused — unused declaration detection.

Note: detect_unused depends on tsc (TypeScript compiler) and a real project setup,
so we test what is feasible: the helper function _categorize_unused and module imports.
"""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _set_project_root(tmp_path, monkeypatch):
    """Point PROJECT_ROOT at the tmp directory."""
    monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))
    import desloppify.utils as utils_mod
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# ── Module import smoke test ─────────────────────────────────


def test_module_imports():
    """Module can be imported without errors."""
    from desloppify.lang.typescript.detectors.unused import (
        detect_unused,
        _categorize_unused,
        TS6133_RE,
        TS6192_RE,
    )
    assert callable(detect_unused)
    assert callable(_categorize_unused)


# ── TS error regex patterns ──────────────────────────────────


class TestErrorRegex:
    def test_ts6133_matches(self):
        """TS6133_RE matches the tsc unused variable error format."""
        from desloppify.lang.typescript.detectors.unused import TS6133_RE

        line = "src/utils.ts(15,7): error TS6133: 'unusedVar' is declared but its value is never read."
        m = TS6133_RE.match(line)
        assert m is not None
        assert m.group(1) == "src/utils.ts"
        assert m.group(2) == "15"
        assert m.group(3) == "7"
        assert m.group(4) == "unusedVar"

    def test_ts6133_no_match_on_other_errors(self):
        """TS6133_RE does not match other tsc errors."""
        from desloppify.lang.typescript.detectors.unused import TS6133_RE

        line = "src/utils.ts(15,7): error TS2304: Cannot find name 'foo'."
        m = TS6133_RE.match(line)
        assert m is None

    def test_ts6192_matches(self):
        """TS6192_RE matches the tsc all-imports-unused error format."""
        from desloppify.lang.typescript.detectors.unused import TS6192_RE

        line = "src/app.ts(1,1): error TS6192: All imports in import declaration are unused."
        m = TS6192_RE.match(line)
        assert m is not None
        assert m.group(1) == "src/app.ts"
        assert m.group(2) == "1"

    def test_ts6192_no_match_on_other(self):
        """TS6192_RE does not match non-6192 lines."""
        from desloppify.lang.typescript.detectors.unused import TS6192_RE

        line = "src/app.ts(1,1): error TS6133: 'x' is declared but its value is never read."
        m = TS6192_RE.match(line)
        assert m is None


# ── _categorize_unused ───────────────────────────────────────


class TestCategorizeUnused:
    def test_import_line(self, tmp_path):
        """Lines starting with 'import' are categorized as imports."""
        from desloppify.lang.typescript.detectors.unused import _categorize_unused

        _write(tmp_path, "app.ts", "import { foo } from './utils';\nconst x = foo();\n")
        result = _categorize_unused(str(tmp_path / "app.ts"), 1)
        assert result == "imports"

    def test_const_line(self, tmp_path):
        """Lines starting with 'const' are categorized as vars."""
        from desloppify.lang.typescript.detectors.unused import _categorize_unused

        _write(tmp_path, "app.ts", "import { foo } from './utils';\nconst unused = 42;\n")
        result = _categorize_unused(str(tmp_path / "app.ts"), 2)
        assert result == "vars"

    def test_let_line(self, tmp_path):
        """Lines starting with 'let' are categorized as vars."""
        from desloppify.lang.typescript.detectors.unused import _categorize_unused

        _write(tmp_path, "app.ts", "let unused = 42;\n")
        result = _categorize_unused(str(tmp_path / "app.ts"), 1)
        assert result == "vars"

    def test_function_line(self, tmp_path):
        """Lines starting with 'function' are categorized as vars."""
        from desloppify.lang.typescript.detectors.unused import _categorize_unused

        _write(tmp_path, "app.ts", "function unused() {}\n")
        result = _categorize_unused(str(tmp_path / "app.ts"), 1)
        assert result == "vars"

    def test_multiline_import(self, tmp_path):
        """Names within multi-line import blocks are categorized as imports."""
        from desloppify.lang.typescript.detectors.unused import _categorize_unused

        _write(tmp_path, "app.ts", (
            "import {\n"
            "  foo,\n"
            "  bar,\n"
            "} from './utils';\n"
        ))
        # Line 3 is 'bar,' which is inside a multi-line import
        result = _categorize_unused(str(tmp_path / "app.ts"), 3)
        assert result == "imports"

    def test_nonexistent_file_defaults_imports(self, tmp_path):
        """Nonexistent file defaults to 'imports' for safety."""
        from desloppify.lang.typescript.detectors.unused import _categorize_unused

        result = _categorize_unused(str(tmp_path / "nonexistent.ts"), 1)
        assert result == "imports"

    def test_export_const_is_vars(self, tmp_path):
        """Lines starting with 'export const' are categorized as vars."""
        from desloppify.lang.typescript.detectors.unused import _categorize_unused

        _write(tmp_path, "app.ts", "export const unused = 42;\n")
        result = _categorize_unused(str(tmp_path / "app.ts"), 1)
        assert result == "vars"
