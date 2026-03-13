"""Tests for desloppify.languages.typescript.detectors.unused — unused declaration detection.

Note: detect_unused depends on tsc (TypeScript compiler) and a real project setup,
so we test what is feasible: the helper function _categorize_unused and module imports.
"""

from pathlib import Path

import pytest

import desloppify.languages.typescript.detectors.unused as ts_unused_mod
from desloppify.languages.typescript.detectors.unused import (
    TS6133_RE,
    TS6192_RE,
    _categorize_unused,
    detect_unused,
)


@pytest.fixture(autouse=True)
def _root(tmp_path, set_project_root):
    """Point PROJECT_ROOT at the tmp directory via RuntimeContext."""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# ── Module import smoke test ─────────────────────────────────


def test_module_imports():
    """Module can be imported without errors."""
    assert callable(detect_unused)
    assert callable(_categorize_unused)
    assert callable(ts_unused_mod._run_tsc_unused_check)


# ── TS error regex patterns ──────────────────────────────────


class TestErrorRegex:
    def test_ts6133_matches(self):
        """TS6133_RE matches the tsc unused variable error format."""

        line = "src/utils.ts(15,7): error TS6133: 'unusedVar' is declared but its value is never read."
        m = TS6133_RE.match(line)
        assert m is not None
        assert m.group(1) == "src/utils.ts"
        assert m.group(2) == "15"
        assert m.group(3) == "7"
        assert m.group(4) == "unusedVar"

    def test_ts6133_no_match_on_other_errors(self):
        """TS6133_RE does not match other tsc errors."""

        line = "src/utils.ts(15,7): error TS2304: Cannot find name 'foo'."
        m = TS6133_RE.match(line)
        assert m is None

    def test_ts6192_matches(self):
        """TS6192_RE matches the tsc all-imports-unused error format."""

        line = "src/app.ts(1,1): error TS6192: All imports in import declaration are unused."
        m = TS6192_RE.match(line)
        assert m is not None
        assert m.group(1) == "src/app.ts"
        assert m.group(2) == "1"

    def test_ts6192_no_match_on_other(self):
        """TS6192_RE does not match non-6192 lines."""

        line = "src/app.ts(1,1): error TS6133: 'x' is declared but its value is never read."
        m = TS6192_RE.match(line)
        assert m is None


# ── _categorize_unused ───────────────────────────────────────


class TestCategorizeUnused:
    def test_import_line(self, tmp_path):
        """Lines starting with 'import' are categorized as imports."""

        _write(tmp_path, "app.ts", "import { foo } from './utils';\nconst x = foo();\n")
        result = _categorize_unused(str(tmp_path / "app.ts"), 1)
        assert result == "imports"

    def test_const_line(self, tmp_path):
        """Lines starting with 'const' are categorized as vars."""

        _write(
            tmp_path, "app.ts", "import { foo } from './utils';\nconst unused = 42;\n"
        )
        result = _categorize_unused(str(tmp_path / "app.ts"), 2)
        assert result == "vars"

    def test_let_line(self, tmp_path):
        """Lines starting with 'let' are categorized as vars."""

        _write(tmp_path, "app.ts", "let unused = 42;\n")
        result = _categorize_unused(str(tmp_path / "app.ts"), 1)
        assert result == "vars"

    def test_function_line(self, tmp_path):
        """Lines starting with 'function' are categorized as vars."""

        _write(tmp_path, "app.ts", "function unused() {}\n")
        result = _categorize_unused(str(tmp_path / "app.ts"), 1)
        assert result == "vars"

    def test_multiline_import(self, tmp_path):
        """Names within multi-line import blocks are categorized as imports."""

        _write(tmp_path, "app.ts", ("import {\n  foo,\n  bar,\n} from './utils';\n"))
        # Line 3 is 'bar,' which is inside a multi-line import
        result = _categorize_unused(str(tmp_path / "app.ts"), 3)
        assert result == "imports"

    def test_nonexistent_file_defaults_imports(self, tmp_path):
        """Nonexistent file defaults to 'imports' for safety."""

        result = _categorize_unused(str(tmp_path / "nonexistent.ts"), 1)
        assert result == "imports"

    def test_export_const_is_vars(self, tmp_path):
        """Lines starting with 'export const' are categorized as vars."""

        _write(tmp_path, "app.ts", "export const unused = 42;\n")
        result = _categorize_unused(str(tmp_path / "app.ts"), 1)
        assert result == "vars"


class TestDenoFallback:
    def test_run_tsc_unused_check_uses_fixed_command(self, tmp_path, monkeypatch):
        class _Result:
            stdout = ""
            stderr = ""

        recorded: dict[str, object] = {}
        npx_path = "/opt/homebrew/bin/npx"

        def _fake_run(*args, **kwargs):
            recorded["args"] = args[0]
            recorded["cwd"] = kwargs["cwd"]
            recorded["timeout"] = kwargs["timeout"]
            return _Result()

        monkeypatch.setattr(ts_unused_mod.shutil, "which", lambda _name: npx_path)
        monkeypatch.setattr(ts_unused_mod._proc_runtime, "run", _fake_run)
        tsconfig = tmp_path / "tsconfig.desloppify.json"
        result = ts_unused_mod._run_tsc_unused_check(tmp_path, tsconfig)

        assert result.stdout == ""
        assert recorded["args"] == [
            npx_path,
            "tsc",
            "--project",
            str(tsconfig),
            "--noEmit",
            ]
        assert recorded["cwd"] == tmp_path
        assert recorded["timeout"] == 120

    def test_run_tsc_unused_check_raises_without_npx(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ts_unused_mod.shutil, "which", lambda _name: None)

        with pytest.raises(OSError, match="TypeScript compiler not found"):
            ts_unused_mod._run_tsc_unused_check(tmp_path, tmp_path / "tsconfig.json")

    def test_detect_unused_uses_deno_fallback_for_url_imports(self, tmp_path, monkeypatch):
        """Deno-style URL imports should bypass tsc and use source-based fallback."""
        _write(
            tmp_path,
            "supabase/functions/edge.ts",
            (
                'import { serve } from "https://deno.land/std@0.177.0/http/server.ts";\n'
                "import { local } from './local.ts';\n"
                "const unusedVar = 1;\n"
                "local();\n"
            ),
        )
        _write(tmp_path, "supabase/functions/local.ts", "export function local() {}\n")

        def _should_not_run(*args, **kwargs):
            raise AssertionError("tsc subprocess should not run in Deno fallback mode")

        monkeypatch.setattr(ts_unused_mod._proc_runtime, "run", _should_not_run)
        entries, total = detect_unused(tmp_path / "supabase/functions")
        names = {entry["name"] for entry in entries}
        assert "serve" in names
        assert "unusedVar" in names
        assert total == 2

    def test_detect_unused_fallback_category_filter(self, tmp_path, monkeypatch):
        """Deno fallback should honor --category filtering."""
        _write(
            tmp_path,
            "supabase/functions/main.ts",
            (
                "import { x } from './dep.ts';\n"
                "const unusedLocal = 1;\n"
                "console.log('hello')\n"
            ),
        )
        _write(tmp_path, "supabase/functions/dep.ts", "export const x = 1;\n")
        monkeypatch.setattr(
            ts_unused_mod._proc_runtime,
            "run",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("tsc subprocess should not run in Deno fallback mode")
            ),
        )

        imports_only, _ = detect_unused(tmp_path / "supabase/functions", "imports")
        vars_only, _ = detect_unused(tmp_path / "supabase/functions", "vars")
        assert all(entry["category"] == "imports" for entry in imports_only)
        assert all(entry["category"] == "vars" for entry in vars_only)
        assert any(entry["name"] == "x" for entry in imports_only)
        assert any(entry["name"] == "unusedLocal" for entry in vars_only)

    def test_detect_unused_non_deno_keeps_tsc_path(self, tmp_path, monkeypatch):
        """Regular TypeScript projects should still parse TS6133/TS6192 from tsc."""
        _write(tmp_path, "src/app.ts", "const x = 1;\n")

        class _Result:
            stdout = (
                "src/app.ts(1,7): error TS6133: 'x' is declared but its value is never read.\n"
            )
            stderr = ""

        calls = {"count": 0}

        def _fake_run(*args, **kwargs):
            calls["count"] += 1
            return _Result()

        monkeypatch.setattr(
            ts_unused_mod.shutil,
            "which",
            lambda name: "/opt/homebrew/bin/npx" if name == "npx" else None,
        )
        monkeypatch.setattr(ts_unused_mod._proc_runtime, "run", _fake_run)
        entries, total = detect_unused(tmp_path / "src")
        assert calls["count"] == 1
        assert total == 1
        assert entries and entries[0]["name"] == "x"

    def test_detect_unused_root_deno_lock_does_not_force_fallback(
        self, tmp_path, monkeypatch
    ):
        """A repo-level deno.lock alone should not disable tsc-based unused detection."""
        _write(tmp_path, "deno.lock", "{}\n")
        _write(tmp_path, "src/app.ts", "const x = 1;\n")

        class _Result:
            stdout = (
                "src/app.ts(1,7): error TS6133: 'x' is declared but its value is never read.\n"
            )
            stderr = ""

        calls = {"count": 0}

        def _fake_run(*args, **kwargs):
            calls["count"] += 1
            return _Result()

        monkeypatch.setattr(
            ts_unused_mod.shutil,
            "which",
            lambda name: "/opt/homebrew/bin/npx" if name == "npx" else None,
        )
        monkeypatch.setattr(ts_unused_mod._proc_runtime, "run", _fake_run)
        entries, total = detect_unused(tmp_path / "src")
        assert calls["count"] == 1
        assert total == 1
        assert entries and entries[0]["name"] == "x"
