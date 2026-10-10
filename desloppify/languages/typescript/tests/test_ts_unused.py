"""Tests for desloppify.languages.typescript.detectors.unused — unused declaration detection.

Compiler integration cases run when tsc is on PATH; unit cases cover discovery
and failure handling without requiring Node.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

import desloppify.languages.typescript.detectors.unused as ts_unused_mod
from desloppify.base.exception_sets import CommandError
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
        assert recorded["args"][:-1] == [
            npx_path,
            "tsc",
            "--project",
            str(tsconfig),
            "--pretty",
            "false",
            "--noEmit",
            "--noUnusedLocals",
            "--noUnusedParameters",
            "--incremental",
            "--tsBuildInfoFile",
        ]
        assert Path(recorded["args"][-1]).name == "unused.tsbuildinfo"
        assert not Path(recorded["args"][-1]).parent.exists()
        assert recorded["cwd"] == tmp_path
        assert recorded["timeout"] == 120

    def test_run_tsc_unused_check_raises_without_npx(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ts_unused_mod.shutil, "which", lambda _name: None)

        with pytest.raises(OSError, match="TypeScript compiler not found"):
            ts_unused_mod._run_tsc_unused_check(tmp_path, tmp_path / "tsconfig.json")

    def test_nested_config_uses_nearest_ancestor_compiler(self, tmp_path, monkeypatch):
        compiler = _write(tmp_path, "packages/app/node_modules/.bin/tsc", "")
        _write(tmp_path, "node_modules/.bin/tsc", "")
        config = _write(tmp_path, "packages/app/config/tsconfig.json", "{}")
        monkeypatch.setattr(ts_unused_mod.shutil, "which", lambda _name: None)
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, "{}", "")

        monkeypatch.setattr(ts_unused_mod._proc_runtime, "run", run)
        ts_unused_mod._run_tsc_unused_check(config.parent, config, show_config=True)
        assert calls[0][0] == str(compiler)

    def test_detect_unused_uses_deno_fallback_for_url_imports(
        self, tmp_path, monkeypatch
    ):
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
        _write(tmp_path, "tsconfig.json", "{}")

        class _Result:
            returncode = 2
            stdout = "src/app.ts(1,7): error TS6133: 'x' is declared but its value is never read.\n"
            stderr = ""

        calls = {"count": 0}

        def _fake_run(*args, **kwargs):
            calls["count"] += 1
            if "--showConfig" in args[0]:
                return subprocess.CompletedProcess(args[0], 0, "{}", "")
            return _Result()

        monkeypatch.setattr(
            ts_unused_mod.shutil,
            "which",
            lambda name: "/opt/homebrew/bin/npx" if name == "npx" else None,
        )
        monkeypatch.setattr(ts_unused_mod._proc_runtime, "run", _fake_run)
        entries, total = detect_unused(tmp_path / "src")
        assert calls["count"] == 2
        assert total == 1
        assert entries and entries[0]["name"] == "x"

    def test_detect_unused_root_deno_lock_does_not_force_fallback(
        self, tmp_path, monkeypatch
    ):
        """A repo-level deno.lock alone should not disable tsc-based unused detection."""
        _write(tmp_path, "deno.lock", "{}\n")
        _write(tmp_path, "src/app.ts", "const x = 1;\n")
        _write(tmp_path, "tsconfig.json", "{}")

        class _Result:
            returncode = 2
            stdout = "src/app.ts(1,7): error TS6133: 'x' is declared but its value is never read.\n"
            stderr = ""

        calls = {"count": 0}

        def _fake_run(*args, **kwargs):
            calls["count"] += 1
            if "--showConfig" in args[0]:
                return subprocess.CompletedProcess(args[0], 0, "{}", "")
            return _Result()

        monkeypatch.setattr(
            ts_unused_mod.shutil,
            "which",
            lambda name: "/opt/homebrew/bin/npx" if name == "npx" else None,
        )
        monkeypatch.setattr(ts_unused_mod._proc_runtime, "run", _fake_run)
        entries, total = detect_unused(tmp_path / "src")
        assert calls["count"] == 2
        assert total == 1
        assert entries and entries[0]["name"] == "x"


class TestProjectConfiguration:
    def test_discovers_nearest_configs_for_nested_projects(self, tmp_path):
        _write(tmp_path, "tsconfig.json", "{}")
        nested = _write(tmp_path, "packages/app/tsconfig.json", "{}")
        _write(tmp_path, "packages/app/tsconfig.app.json", "{}")
        other = _write(tmp_path, "packages/other/tsconfig.app.json", "{}")
        files = [
            _write(tmp_path, "packages/app/src/code.ts", "export {};"),
            _write(tmp_path, "packages/other/src/code.ts", "export {};"),
        ]
        assert ts_unused_mod._find_tsconfigs([str(path) for path in files]) == [
            nested,
            other,
        ]

    @pytest.mark.parametrize(
        "diagnostic",
        [
            "error TS5083: Cannot read file 'missing.json'.",
            "tsconfig.json(2,2): error TS5023: Unknown compiler option 'broken'.",
        ],
    )
    def test_config_errors_are_not_reported_as_unused_results(
        self, tmp_path, monkeypatch, diagnostic
    ):
        _write(tmp_path, "tsconfig.json", "{}")
        _write(tmp_path, "src/app.ts", "export {}; const unused = 1;")

        def run(_root, _config, *, show_config=False):
            assert show_config
            return subprocess.CompletedProcess([], 1, diagnostic, "")

        monkeypatch.setattr(ts_unused_mod, "_run_tsc_unused_check", run)
        with pytest.raises(
            CommandError, match="Cannot read TypeScript project"
        ) as error:
            detect_unused(tmp_path)
        assert diagnostic in str(error.value)
        assert not (tmp_path / "tsconfig.desloppify.json").exists()

    @pytest.mark.parametrize(
        "result",
        [
            subprocess.CompletedProcess([], 1, "", "compiler failed"),
            subprocess.CompletedProcess(
                [], 2, "error TS2688: Cannot find type definition file for 'node'.", ""
            ),
            subprocess.CompletedProcess(
                [],
                2,
                "tsconfig.json(1,41): error TS6304: Composite projects may not disable declaration emit.",
                "",
            ),
            subprocess.CompletedProcess(
                [],
                -9,
                "src/app.ts(1,18): error TS6133: 'unused' is declared but its value is never read.",
                "compiler terminated",
            ),
        ],
    )
    def test_compiler_failures_do_not_become_a_clean_check(
        self, tmp_path, monkeypatch, result
    ):
        _write(tmp_path, "tsconfig.json", "{}")
        _write(tmp_path, "src/app.ts", "export {};")
        monkeypatch.setattr(
            ts_unused_mod,
            "_run_tsc_unused_check",
            lambda _root, _config, *, show_config=False: (
                subprocess.CompletedProcess([], 0, "{}", "") if show_config else result
            ),
        )
        with pytest.raises(CommandError, match="TypeScript unused check failed"):
            detect_unused(tmp_path)

    def test_source_type_errors_can_coexist_with_unused_findings(
        self, tmp_path, monkeypatch
    ):
        _write(tmp_path, "tsconfig.json", "{}")
        _write(tmp_path, "src/app.ts", "export {}; const unused = 1;")
        monkeypatch.setattr(
            ts_unused_mod,
            "_run_tsc_unused_check",
            lambda _root, _config, *, show_config=False: subprocess.CompletedProcess(
                [],
                0 if show_config else 2,
                "{}"
                if show_config
                else "src/app.ts(1,8): error TS2304: Cannot find name 'missing'.\n"
                "src/app.ts(1,18): error TS6133: 'unused' is declared but its value is never read.",
                "",
            ),
        )
        entries, _ = detect_unused(tmp_path)
        assert [entry["name"] for entry in entries] == ["unused"]

    def test_compiler_unavailable_does_not_bypass_project_exclusions(
        self, tmp_path, monkeypatch
    ):
        _write(tmp_path, "tsconfig.json", '{"exclude":["src/excluded.ts"]}')
        _write(tmp_path, "src/excluded.ts", "const unused = 1;")

        def unavailable(*args, **kwargs):
            raise OSError("compiler not found")

        monkeypatch.setattr(ts_unused_mod, "_run_tsc_unused_check", unavailable)
        with pytest.raises(CommandError, match="compiler not found"):
            detect_unused(tmp_path)

    def test_missing_configuration_reports_source_fallback(self, tmp_path, caplog):
        _write(tmp_path, "src/app.ts", "const unused = 1;")
        entries, _ = detect_unused(tmp_path)
        assert entries[0]["name"] == "unused"
        assert "No TypeScript project configuration found" in caplog.text


@pytest.fixture
def real_tsc(monkeypatch):
    compiler = shutil.which("tsc")
    if compiler is None:
        pytest.skip("TypeScript compiler is not installed")
    # Use the installed compiler directly; integration tests never fetch npm packages.
    monkeypatch.setattr(
        ts_unused_mod.shutil, "which", lambda name: compiler if name == "tsc" else None
    )
    return compiler


class TestRealProjectConfiguration:
    def test_external_scan_path_preserves_its_project_excludes(
        self, tmp_path_factory, real_tsc
    ):
        external = tmp_path_factory.mktemp("external-project")
        _write(
            external,
            "tsconfig.json",
            '{"include":["src"],"exclude":["src/excluded.ts"]}',
        )
        _write(external, "src/excluded.ts", "export {}; const excluded = 1;")
        _write(external, "src/included.ts", "export {}; const included = 1;")
        entries, _ = detect_unused(external / "src")
        assert [entry["name"] for entry in entries] == ["included"]

    @pytest.mark.parametrize(
        "options, diagnostic",
        [
            ('"composite":true,"declaration":false', "TS6304"),
            ('"emitDeclarationOnly":true,"declaration":false', "TS5069"),
        ],
    )
    def test_compile_stage_configuration_errors_are_reported(
        self, tmp_path, real_tsc, options, diagnostic
    ):
        _write(tmp_path, "tsconfig.json", '{"compilerOptions":{' + options + "}}")
        _write(tmp_path, "src/app.ts", "export {}; const unused = 1;")
        with pytest.raises(CommandError, match=diagnostic):
            detect_unused(tmp_path)

    def test_jsonc_extends_and_excludes_survive_nested_scan(self, tmp_path, real_tsc):
        _write(
            tmp_path,
            "app/base.json",
            '{"compilerOptions":{"noEmit":true,"skipLibCheck":true},"include":["src"],"exclude":["src/excluded.ts"]}',
        )
        _write(
            tmp_path,
            "app/tsconfig.json",
            '{// JSONC belongs to TypeScript, not Python\n"extends":"./base.json",}',
        )
        _write(tmp_path, "app/src/excluded.ts", "export {}; const excluded = 1;")
        _write(tmp_path, "app/src/included.ts", "export {}; const included = 1;")
        entries, _ = detect_unused(tmp_path / "app/src")
        assert [
            (entry["file"], entry["name"], entry["category"]) for entry in entries
        ] == [("app/src/included.ts", "included", "vars")]
        assert not list(tmp_path.rglob("*.tsbuildinfo"))
        assert not list(tmp_path.rglob("tsconfig.desloppify.json"))

    def test_solution_config_checks_references_and_deduplicates(
        self, tmp_path, real_tsc
    ):
        _write(
            tmp_path,
            "tsconfig.json",
            '{"files":[],"references":[{"path":"./tsconfig.app.json"},{"path":"./tsconfig.app.json"}]}',
        )
        _write(
            tmp_path,
            "tsconfig.app.json",
            '{"compilerOptions":{"composite":true},"include":["src"]}',
        )
        _write(tmp_path, "src/included.ts", "export {}; const included = 1;")
        entries, _ = detect_unused(tmp_path)
        assert [entry["name"] for entry in entries] == ["included"]
        assert not list(tmp_path.rglob("*.tsbuildinfo"))

    def test_scan_root_discovers_sibling_packages_and_filters_outside_scope(
        self, tmp_path, real_tsc
    ):
        for package in ("app", "other"):
            _write(tmp_path, f"packages/{package}/tsconfig.json", '{"include":["src"]}')
            _write(
                tmp_path,
                f"packages/{package}/src/index.ts",
                f"export {{}}; const unused_{package} = 1;",
            )
        entries, _ = detect_unused(tmp_path)
        assert {entry["file"] for entry in entries} == {
            "packages/app/src/index.ts",
            "packages/other/src/index.ts",
        }
        entries, _ = detect_unused(tmp_path / "packages/app/src")
        assert [entry["file"] for entry in entries] == ["packages/app/src/index.ts"]

    def test_missing_extended_config_raises_instead_of_scanning_defaults(
        self, tmp_path, real_tsc
    ):
        _write(tmp_path, "tsconfig.json", '{"extends":"./missing.json"}')
        _write(tmp_path, "src/app.ts", "export {}; const unused = 1;")
        with pytest.raises(CommandError, match="missing.json"):
            detect_unused(tmp_path)
