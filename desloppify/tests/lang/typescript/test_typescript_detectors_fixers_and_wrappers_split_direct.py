"""Direct tests for split TypeScript detector/fixer/wrapper helper modules."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import desloppify.languages.typescript._detectors as ts_detectors_mod
import desloppify.languages.typescript._fixers as ts_fixers_mod
import desloppify.languages.typescript.commands_wrappers as ts_cmds_mod
import desloppify.languages.typescript.detectors.security as ts_security_mod
import desloppify.languages.typescript.detectors.smells_assets as ts_assets_mod
import desloppify.languages.typescript.detectors.unused_fallback as ts_unused_mod
from desloppify.languages._framework.base.types import DetectorPhase


def test_ts_detector_helpers_cover_treesitter_and_function_extraction(monkeypatch) -> None:
    monkeypatch.setattr("desloppify.languages._framework.treesitter.is_available", lambda: False)
    assert ts_detectors_mod.ts_treesitter_phases() == []

    monkeypatch.setattr("desloppify.languages._framework.treesitter.is_available", lambda: True)
    monkeypatch.setattr("desloppify.languages._framework.treesitter.get_spec", lambda _lang: SimpleNamespace())
    monkeypatch.setattr(ts_detectors_mod, "make_cohesion_phase", lambda _spec: DetectorPhase("Cohesion", lambda *_args: ([], {})))
    phases = ts_detectors_mod.ts_treesitter_phases()
    assert len(phases) == 1
    assert phases[0].label == "Cohesion"

    monkeypatch.setattr(
        ts_detectors_mod,
        "find_ts_files",
        lambda _path: ["src/a.ts", "src/types.d.ts", "node_modules/pkg/index.ts", "src/b.tsx"],
    )
    monkeypatch.setattr(ts_detectors_mod, "extract_ts_functions", lambda filepath: [SimpleNamespace(file=filepath)])
    functions = ts_detectors_mod.ts_extract_functions(Path("."))
    assert [fn.file for fn in functions] == ["src/a.ts", "src/b.tsx"]


def test_ts_fixer_helpers_and_registry(monkeypatch) -> None:
    monkeypatch.setattr(ts_fixers_mod.unused_detector_mod, "detect_unused", lambda _path, category: ([{"name": category}], 1))
    monkeypatch.setattr(ts_fixers_mod.logs_detector_mod, "detect_logs", lambda _path: ([{"name": "log"}], 1))
    monkeypatch.setattr(
        ts_fixers_mod.smells_detector_mod,
        "detect_smells",
        lambda _path: (
            [
                {"id": "dead_useeffect", "matches": [{"name": "effect"}]},
                {"id": "empty_if_chain", "matches": [{"name": "if"}]},
            ],
            2,
        ),
    )

    class _Fixers:
        @staticmethod
        def fix_unused_imports(entries, *, dry_run=False):
            return SimpleNamespace(entries=entries, dry_run=dry_run)

        @staticmethod
        def fix_debug_logs(entries, *, dry_run=False):
            return SimpleNamespace(entries=[{"tags": ["debug"]}], dry_run=dry_run)

        @staticmethod
        def fix_unused_vars(entries, *, dry_run=False):
            return SimpleNamespace(entries=entries, dry_run=dry_run)

        @staticmethod
        def fix_unused_params(entries, *, dry_run=False):
            return SimpleNamespace(entries=entries, dry_run=dry_run)

        @staticmethod
        def fix_dead_useeffect(entries, *, dry_run=False):
            return SimpleNamespace(entries=entries, dry_run=dry_run)

        @staticmethod
        def fix_empty_if_chain(entries, *, dry_run=False):
            return SimpleNamespace(entries=entries, dry_run=dry_run)

    monkeypatch.setattr(ts_fixers_mod, "_ts_fixers_mod", lambda: _Fixers)

    assert ts_fixers_mod._det_unused("imports")(Path("."))[0]["name"] == "imports"
    assert ts_fixers_mod._det_logs(Path("."))[0]["name"] == "log"
    assert ts_fixers_mod._det_smell("dead_useeffect")(Path("."))[0]["name"] == "effect"

    fixed_logs = ts_fixers_mod._fix_logs([{"name": "debug"}], dry_run=True)
    assert fixed_logs.entries[0]["removed"] == ["debug"]

    fixers = ts_fixers_mod.get_ts_fixers()
    assert set(fixers.keys()) == {
        "unused-imports",
        "debug-logs",
        "unused-vars",
        "unused-params",
        "dead-useeffect",
        "empty-if-chain",
    }
    assert fixers["unused-imports"].detector == "unused"
    assert fixers["debug-logs"].detector == "logs"


def test_ts_security_detector_reports_line_and_file_level_issues(tmp_path) -> None:
    page = tmp_path / "src" / "page.ts"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        "\n".join(
            [
                "const x = eval(userInput)",
                "element.innerHTML = html",
                "window.location = data.url",
                "const payload = atob(token.split('.')[1])",
            ]
        ),
        encoding="utf-8",
    )

    edge = tmp_path / "supabase" / "functions" / "foo" / "index.ts"
    edge.parent.mkdir(parents=True, exist_ok=True)
    edge.write_text(
        "Deno.serve(async (req) => {\nconst a = JSON.parse(x)\nreturn new Response('ok')\n}",
        encoding="utf-8",
    )

    sql = tmp_path / "db" / "schema.sql"
    sql.parent.mkdir(parents=True, exist_ok=True)
    sql.write_text("CREATE VIEW public.foo AS SELECT 1;", encoding="utf-8")

    result = ts_security_mod.detect_ts_security_result(
        [str(page), str(edge), str(sql)],
        zone_map=None,
    )
    kinds = {entry["detail"]["kind"] for entry in result.entries}

    assert result.population_size == 3
    assert "eval_injection" in kinds
    assert "innerHTML_assignment" in kinds
    assert "open_redirect" in kinds
    assert "unverified_jwt_decode" in kinds
    assert "edge_function_missing_auth" in kinds
    assert "json_parse_unguarded" in kinds
    assert "rls_bypass_views" in kinds


def test_ts_asset_smells_and_unused_fallback_helpers(monkeypatch, tmp_path) -> None:
    assert ts_assets_mod._script_is_documented("Use `npm run test` and `pnpm lint`", "test") is True
    assert ts_assets_mod._script_is_documented("No commands", "build") is False

    css = tmp_path / "styles.css"
    css.write_text("\n".join([".x { color: red !important; }"] * 320), encoding="utf-8")
    (tmp_path / "README.md").write_text("Project docs\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"dev": "vite", "build": "vite build", "test": "vitest", "lint": "eslint"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(ts_assets_mod, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(ts_assets_mod, "find_source_files", lambda _path, _exts: [str(css)])

    smell_counts = {
        "css_monolith": [],
        "css_important_overuse": [],
        "docs_scripts_drift": [],
    }
    scanned = ts_assets_mod.detect_non_ts_asset_smells(tmp_path, smell_counts)
    assert scanned == 2
    assert smell_counts["css_monolith"]
    assert smell_counts["css_important_overuse"]
    assert smell_counts["docs_scripts_drift"]

    assert ts_unused_mod._identifier_occurrences("const x = x + 1", "x") == 2
    assert ts_unused_mod._extract_import_names("import a, { b as c, type D } from './m'") == ["a", "c", "D"]
    assert ts_unused_mod._extract_import_names("const x = 1") == []

    ts_file = tmp_path / "src.ts"
    ts_file.write_text(
        "\n".join(
            [
                "import { used, unusedItem } from './mod'",
                "const live = used + 1",
                "const deadVar = 1",
                "console.log(live)",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(ts_unused_mod, "find_ts_files", lambda _path: [str(ts_file)])
    monkeypatch.setattr(ts_unused_mod, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(ts_unused_mod, "read_file_text", lambda filepath: Path(filepath).read_text(encoding="utf-8"))

    unused_entries, scanned_files = ts_unused_mod.detect_unused_fallback(tmp_path, "all")
    categories = {entry["category"] for entry in unused_entries}
    assert scanned_files == 1
    assert "imports" in categories
    assert "vars" in categories

    deno_root = tmp_path / "deno-app"
    deno_root.mkdir(parents=True, exist_ok=True)
    (deno_root / "deno.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ts_unused_mod, "get_project_root", lambda: deno_root)
    assert ts_unused_mod._contains_deno_markers(deno_root / "src") is True

    deno_file = deno_root / "mod.ts"
    deno_file.write_text("import x from 'https://deno.land/x/mod.ts'\n", encoding="utf-8")
    assert ts_unused_mod._has_deno_import_syntax([str(deno_file)]) is True
    assert ts_unused_mod.should_use_deno_fallback(Path("/tmp/supabase/functions/foo"), []) is True


def test_ts_command_wrappers_cover_json_rendering_and_dispatch(monkeypatch, tmp_path) -> None:
    printed: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: printed.append(" ".join(str(a) for a in args)))
    monkeypatch.setattr(ts_cmds_mod, "colorize", lambda text, _style: text)
    monkeypatch.setattr(ts_cmds_mod, "print_table", lambda *args, **kwargs: printed.append("TABLE"))

    monkeypatch.setattr(ts_cmds_mod.deps_detector_mod, "build_dep_graph", lambda _path: {"src/a.ts": {"imports": set(), "importers": set(), "import_count": 0, "importer_count": 0}})
    monkeypatch.setattr(
        ts_cmds_mod.orphaned_detector_mod,
        "detect_orphaned_files",
        lambda *_args, **_kwargs: ([{"file": "src/a.ts", "loc": 10}], 1),
    )

    ts_cmds_mod.cmd_orphaned(SimpleNamespace(path=str(tmp_path), json=True, top=5))
    orphan_payload = json.loads(printed[-1])
    assert orphan_payload["count"] == 1

    monkeypatch.setattr(ts_cmds_mod, "find_ts_files", lambda _path: ["src/a.ts", "node_modules/x.ts", "src/types.d.ts"])
    monkeypatch.setattr(ts_cmds_mod, "extract_ts_functions", lambda filepath: [SimpleNamespace(name="fn", file=filepath, line=1, loc=4)])
    monkeypatch.setattr(
        ts_cmds_mod.dupes_detector_mod,
        "detect_duplicates",
        lambda _functions, threshold: (
            [
                {
                    "kind": "exact",
                    "fn_a": {"name": "a", "file": "src/a.ts", "line": 1, "loc": 4},
                    "fn_b": {"name": "b", "file": "src/b.ts", "line": 2, "loc": 4},
                    "similarity": 1.0,
                },
                {
                    "kind": "near-duplicate",
                    "fn_a": {"name": "a", "file": "src/a.ts", "line": 1, "loc": 4},
                    "fn_b": {"name": "c", "file": "src/c.ts", "line": 3, "loc": 6},
                    "similarity": 0.88,
                },
            ],
            2,
        ),
    )

    printed.clear()
    ts_cmds_mod.cmd_dupes(SimpleNamespace(path=str(tmp_path), json=False, top=5, threshold=0.8))
    assert any("Exact duplicates" in line for line in printed)
    assert any("Near-duplicates" in line for line in printed)
    assert "TABLE" in printed

    printed.clear()
    ts_cmds_mod.cmd_dupes(SimpleNamespace(path=str(tmp_path), json=True, top=5, threshold=0.8))
    dupes_payload = json.loads(printed[-1])
    assert dupes_payload["count"] == 2

    display_calls: list[dict] = []
    monkeypatch.setattr(ts_cmds_mod, "display_entries", lambda args, entries, **kwargs: display_calls.append({"args": args, "entries": entries, **kwargs}))
    monkeypatch.setattr(ts_cmds_mod, "extract_ts_components", lambda _path: ["Comp"])
    monkeypatch.setattr(ts_cmds_mod.gods_detector_mod, "detect_gods", lambda _components, _rules: ([{"file": "src/App.tsx", "loc": 200, "detail": {"hook_total": 5}, "reasons": ["long"]}], 1))

    ts_cmds_mod.cmd_gods(SimpleNamespace(path=str(tmp_path), json=False, top=5))
    assert display_calls and display_calls[0]["label"] == "God components"

    monkeypatch.setattr(ts_cmds_mod, "get_src_path", lambda: "src")
    monkeypatch.setattr(ts_cmds_mod.coupling_detector_mod, "detect_coupling_violations", lambda *_args, **_kwargs: ([{"file": "src/shared/a.ts", "target": "src/tools/x.ts", "tool": "x"}], 1))
    monkeypatch.setattr(ts_cmds_mod.coupling_detector_mod, "detect_boundary_candidates", lambda *_args, **_kwargs: ([{"file": "src/shared/only.ts", "loc": 20, "sole_tool": "x", "importer_count": 1}], 1))
    monkeypatch.setattr(ts_cmds_mod.coupling_detector_mod, "detect_cross_tool_imports", lambda *_args, **_kwargs: ([{"file": "src/tools/a.ts", "target": "src/tools/b.ts", "source_tool": "a", "target_tool": "b"}], 1))

    printed.clear()
    ts_cmds_mod.cmd_coupling(SimpleNamespace(path=str(tmp_path), json=True, top=5))
    coupling_payload = json.loads(printed[-1])
    assert coupling_payload["violations"] == 1
    assert coupling_payload["boundary_candidates"] == 1

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(ts_cmds_mod, "_run_detector_cmd", lambda _args, module_path, fn_name: calls.append((module_path, fn_name)))
    args = SimpleNamespace(path=str(tmp_path), json=False, top=5)
    ts_cmds_mod.cmd_logs(args)
    ts_cmds_mod.cmd_unused(args)
    ts_cmds_mod.cmd_exports(args)
    ts_cmds_mod.cmd_deprecated(args)
    ts_cmds_mod.cmd_props(args)
    ts_cmds_mod.cmd_concerns(args)
    ts_cmds_mod.cmd_deps(args)
    ts_cmds_mod.cmd_cycles(args)
    ts_cmds_mod.cmd_patterns(args)
    ts_cmds_mod.cmd_react(args)

    assert calls == [
        (".detectors.logs", "cmd_logs"),
        (".detectors.unused", "cmd_unused"),
        (".detectors.exports", "cmd_exports"),
        (".detectors.deprecated", "cmd_deprecated"),
        (".detectors.props", "cmd_props"),
        (".detectors.concerns", "cmd_concerns"),
        (".detectors.deps", "cmd_deps"),
        (".detectors.deps", "cmd_cycles"),
        (".detectors.patterns_cli", "cmd_patterns"),
        (".detectors.react_cli", "cmd_react"),
    ]
