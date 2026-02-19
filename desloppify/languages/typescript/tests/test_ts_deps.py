"""Tests for desloppify.languages.typescript.detectors.deps — dependency graph and import analysis."""

import json
from pathlib import Path

import pytest

import desloppify.languages.typescript.detectors.deps as deps_detector_mod
import desloppify.utils as utils_mod
from desloppify.engine.detectors import orphaned as orphaned_detector_mod
from desloppify.languages.typescript.detectors.exports import _build_reference_index


@pytest.fixture(autouse=True)
def _set_project_root(tmp_path, monkeypatch):
    """Point PROJECT_ROOT and SRC_PATH at the tmp directory."""
    monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(utils_mod, "SRC_PATH", tmp_path / "src")
    monkeypatch.setattr(deps_detector_mod, "PROJECT_ROOT", tmp_path)
    # Clear caches so each test starts fresh
    utils_mod._find_source_files_cached.cache_clear()
    deps_detector_mod._load_tsconfig_paths_cached.cache_clear()


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# ── build_dep_graph ──────────────────────────────────────────


class TestBuildDepGraph:
    def test_simple_relative_import(self, tmp_path):
        """Graph captures a simple relative import between two files."""

        _write(tmp_path, "utils.ts", "export function foo() { return 1; }\n")
        _write(
            tmp_path, "main.ts", "import { foo } from './utils';\nconsole.log(foo());\n"
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        main_key = str((tmp_path / "main.ts").resolve())
        utils_key = str((tmp_path / "utils.ts").resolve())

        assert main_key in graph
        assert utils_key in graph[main_key]["imports"]
        assert main_key in graph[utils_key]["importers"]

    def test_import_with_extension(self, tmp_path):
        """Graph resolves imports where the file has a .ts extension match."""

        _write(tmp_path, "helpers.ts", "export const x = 1;\n")
        _write(tmp_path, "app.ts", "import { x } from './helpers';\n")

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        app_key = str((tmp_path / "app.ts").resolve())
        helpers_key = str((tmp_path / "helpers.ts").resolve())
        assert helpers_key in graph[app_key]["imports"]

    def test_import_tsx_file(self, tmp_path):
        """Graph resolves imports to .tsx files."""

        _write(tmp_path, "Button.tsx", "export const Button = () => <button />;\n")
        _write(tmp_path, "App.tsx", "import { Button } from './Button';\n")

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        app_key = str((tmp_path / "App.tsx").resolve())
        button_key = str((tmp_path / "Button.tsx").resolve())
        assert button_key in graph[app_key]["imports"]

    def test_import_with_js_specifier_resolves_ts_file(self, tmp_path):
        """NodeNext-style `./x.js` specifiers resolve to source `x.ts` files."""

        _write(tmp_path, "helpers.ts", "export const x = 1;\n")
        _write(tmp_path, "app.ts", "import { x } from './helpers.js';\n")

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        app_key = str((tmp_path / "app.ts").resolve())
        helpers_key = str((tmp_path / "helpers.ts").resolve())
        assert helpers_key in graph[app_key]["imports"]

    def test_index_file_resolution(self, tmp_path):
        """Graph resolves directory imports to index.ts files."""

        _write(tmp_path, "components/index.ts", "export const Comp = 'comp';\n")
        _write(tmp_path, "main.ts", "import { Comp } from './components';\n")

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        main_key = str((tmp_path / "main.ts").resolve())
        index_key = str((tmp_path / "components" / "index.ts").resolve())
        assert index_key in graph[main_key]["imports"]

    def test_no_external_packages_in_graph(self, tmp_path):
        """External package imports (non-relative, non-alias) should not appear in the graph."""

        _write(
            tmp_path,
            "app.ts",
            "import React from 'react';\nimport { useState } from 'react';\n",
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        # Only the app.ts file should be in the graph (as a node), no react entries
        for key in graph:
            assert "react" not in Path(key).name

    def test_graph_has_counts(self, tmp_path):
        """Graph entries should have import_count and importer_count fields."""

        _write(tmp_path, "a.ts", "export const a = 1;\n")
        _write(tmp_path, "b.ts", "import { a } from './a';\nexport const b = a;\n")

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        a_key = str((tmp_path / "a.ts").resolve())
        b_key = str((tmp_path / "b.ts").resolve())
        assert graph[a_key]["importer_count"] == 1
        assert graph[b_key]["import_count"] == 1

    def test_empty_directory(self, tmp_path):
        """Empty directory returns an empty graph."""

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        assert graph == {}

    def test_multiple_imports_from_same_file(self, tmp_path):
        """Multiple import lines from the same source still yield one edge."""

        _write(tmp_path, "utils.ts", "export const a = 1;\nexport const b = 2;\n")
        _write(
            tmp_path,
            "main.ts",
            ("import { a } from './utils';\nimport { b } from './utils';\n"),
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        main_key = str((tmp_path / "main.ts").resolve())
        utils_key = str((tmp_path / "utils.ts").resolve())
        # imports is a set, so duplicates are collapsed
        assert utils_key in graph[main_key]["imports"]
        assert graph[main_key]["import_count"] == 1

    def test_side_effect_import_creates_graph_edge(self, tmp_path):
        """Side-effect imports (`import './x'`) should be reflected in the dep graph."""
        _write(tmp_path, "polyfill.ts", "export const p = 1;\n")
        _write(tmp_path, "main.ts", "import './polyfill';\n")

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        main_key = str((tmp_path / "main.ts").resolve())
        polyfill_key = str((tmp_path / "polyfill.ts").resolve())
        assert polyfill_key in graph[main_key]["imports"]

    def test_deno_url_imports_record_external_dependencies(self, tmp_path):
        """Deno URL imports should be parsed and tracked as external imports."""
        _write(tmp_path, "dep.ts", "export const dep = 1;\n")
        _write(
            tmp_path,
            "main.ts",
            (
                'import { serve } from "https://deno.land/std@0.177.0/http/server.ts";\n'
                "import { dep } from './dep';\n"
            ),
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        main_key = str((tmp_path / "main.ts").resolve())
        dep_key = str((tmp_path / "dep.ts").resolve())
        assert dep_key in graph[main_key]["imports"]
        assert (
            "https://deno.land/std@0.177.0/http/server.ts"
            in graph[main_key]["external_imports"]
        )

    def test_bidirectional_import(self, tmp_path):
        """Two files importing each other creates bidirectional edges."""

        _write(
            tmp_path, "a.ts", "import { bVal } from './b';\nexport const aVal = 1;\n"
        )
        _write(
            tmp_path, "b.ts", "import { aVal } from './a';\nexport const bVal = 2;\n"
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        a_key = str((tmp_path / "a.ts").resolve())
        b_key = str((tmp_path / "b.ts").resolve())
        assert b_key in graph[a_key]["imports"]
        assert a_key in graph[b_key]["imports"]

    def test_js_specifier_imports_do_not_create_false_orphans(self, tmp_path):
        """Files imported through `./x.js` should not be flagged as orphaned."""

        _write(tmp_path, "shared.ts", "export const shared = 1;\n")
        _write(
            tmp_path,
            "utils.ts",
            "import { shared } from './shared.js';\nexport const x = shared;\n",
        )
        _write(tmp_path, "main.ts", "import { x } from './utils.js';\nconsole.log(x)\n")

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        utils_key = str((tmp_path / "utils.ts").resolve())
        assert graph[utils_key]["importer_count"] == 1

        orphans, _ = orphaned_detector_mod.detect_orphaned_files(
            tmp_path,
            graph,
            extensions=[".ts", ".tsx"],
            options=orphaned_detector_mod.OrphanedDetectionOptions(
                extra_entry_patterns=[],
                extra_barrel_names=set(),
            ),
        )
        orphan_files = {entry["file"] for entry in orphans}
        assert utils_key not in orphan_files


# ── ts_alias_resolver ────────────────────────────────────────


class TestTsAliasResolver:
    def test_resolves_at_alias(self):
        assert (
            deps_detector_mod.ts_alias_resolver("@/components/Button")
            == "src/components/Button"
        )

    def test_passthrough_relative(self):
        assert deps_detector_mod.ts_alias_resolver("./utils") == "./utils"

    def test_passthrough_package(self):
        assert deps_detector_mod.ts_alias_resolver("react") == "react"


# ── build_dynamic_import_targets ─────────────────────────────


class TestBuildDynamicImportTargets:
    def test_finds_dynamic_import(self, tmp_path):
        """Finds files referenced by dynamic import() expressions."""

        _write(tmp_path, "app.ts", "const mod = import('./lazy');\n")

        targets = deps_detector_mod.build_dynamic_import_targets(
            tmp_path, [".ts", ".tsx"]
        )
        assert "./lazy" in targets

    def test_finds_side_effect_import(self, tmp_path):
        """Finds side-effect imports (import 'module')."""

        _write(tmp_path, "app.ts", "import './polyfill';\n")

        targets = deps_detector_mod.build_dynamic_import_targets(
            tmp_path, [".ts", ".tsx"]
        )
        assert "./polyfill" in targets

    def test_empty_directory(self, tmp_path):
        """Empty directory returns empty set."""

        targets = deps_detector_mod.build_dynamic_import_targets(
            tmp_path, [".ts", ".tsx"]
        )
        assert targets == set()

    def test_finds_dynamic_import_in_svelte(self, tmp_path):
        """Dynamic imports in .svelte files are discovered."""

        _write(
            tmp_path,
            "App.svelte",
            '<script>\nconst mod = import("./lazy");\n</script>\n',
        )
        targets = deps_detector_mod.build_dynamic_import_targets(
            tmp_path, [".ts", ".tsx"]
        )
        assert "./lazy" in targets


# ── tsconfig paths ──────────────────────────────────────────────


class TestTsconfigPaths:
    def test_basic_paths(self, tmp_path):
        """Basic @/* path alias resolved from tsconfig.json."""
        _write(
            tmp_path,
            "tsconfig.json",
            json.dumps({"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}),
        )
        paths = deps_detector_mod._load_tsconfig_paths(tmp_path)
        assert paths == {"@/": "src/"}

    def test_multiple_aliases(self, tmp_path):
        """Multiple path aliases all resolve correctly."""
        _write(
            tmp_path,
            "tsconfig.json",
            json.dumps(
                {
                    "compilerOptions": {
                        "paths": {
                            "@/*": ["./src/*"],
                            "@components/*": ["./src/components/*"],
                            "@utils/*": ["./src/utils/*"],
                        }
                    }
                }
            ),
        )
        paths = deps_detector_mod._load_tsconfig_paths(tmp_path)
        assert paths["@/"] == "src/"
        assert paths["@components/"] == "src/components/"
        assert paths["@utils/"] == "src/utils/"

    def test_with_base_url(self, tmp_path):
        """baseUrl composes with path targets."""
        _write(
            tmp_path,
            "tsconfig.json",
            json.dumps(
                {
                    "compilerOptions": {
                        "baseUrl": "src",
                        "paths": {"@lib/*": ["./lib/*"]},
                    }
                }
            ),
        )
        paths = deps_detector_mod._load_tsconfig_paths(tmp_path)
        assert paths["@lib/"] == "src/lib/"

    def test_extends_inherits_paths(self, tmp_path):
        """Child tsconfig inherits paths from parent via extends."""
        _write(
            tmp_path,
            "tsconfig.base.json",
            json.dumps(
                {"compilerOptions": {"paths": {"@shared/*": ["./packages/shared/*"]}}}
            ),
        )
        _write(
            tmp_path,
            "tsconfig.json",
            json.dumps({"extends": "./tsconfig.base.json", "compilerOptions": {}}),
        )
        paths = deps_detector_mod._load_tsconfig_paths(tmp_path)
        assert paths["@shared/"] == "packages/shared/"

    def test_missing_fallback(self, tmp_path):
        """No tsconfig at all returns @/ → src/ fallback."""
        paths = deps_detector_mod._load_tsconfig_paths(tmp_path)
        assert paths == {"@/": "src/"}

    def test_malformed_json(self, tmp_path):
        """Malformed JSON gracefully falls back."""
        _write(tmp_path, "tsconfig.json", "{ invalid json !!!")
        paths = deps_detector_mod._load_tsconfig_paths(tmp_path)
        assert paths == {"@/": "src/"}

    def test_tsconfig_no_paths_field(self, tmp_path):
        """tsconfig exists but has no paths field → fallback."""
        _write(
            tmp_path, "tsconfig.json", json.dumps({"compilerOptions": {"strict": True}})
        )
        paths = deps_detector_mod._load_tsconfig_paths(tmp_path)
        assert paths == {"@/": "src/"}

    def test_alias_resolver_uses_tsconfig(self, tmp_path):
        """deps_detector_mod.ts_alias_resolver() respects tsconfig paths."""
        _write(
            tmp_path,
            "tsconfig.json",
            json.dumps({"compilerOptions": {"paths": {"@lib/*": ["./lib/*"]}}}),
        )
        assert deps_detector_mod.ts_alias_resolver("@lib/utils") == "lib/utils"
        # Non-matching paths pass through
        assert deps_detector_mod.ts_alias_resolver("react") == "react"
        assert deps_detector_mod.ts_alias_resolver("./local") == "./local"

    def test_graph_resolves_tsconfig_alias(self, tmp_path):
        """build_dep_graph uses tsconfig paths to resolve aliases."""
        _write(
            tmp_path,
            "tsconfig.json",
            json.dumps({"compilerOptions": {"paths": {"@lib/*": ["./lib/*"]}}}),
        )
        _write(tmp_path, "lib/helpers.ts", "export const help = 1;\n")
        _write(tmp_path, "app.ts", "import { help } from '@lib/helpers';\n")

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        app_key = str((tmp_path / "app.ts").resolve())
        helpers_key = str((tmp_path / "lib/helpers.ts").resolve())
        assert helpers_key in graph[app_key]["imports"]
        assert app_key in graph[helpers_key]["importers"]

    def test_cache_keyed_by_root(self, tmp_path):
        """Cache returns same result on second call without re-parsing."""
        _write(
            tmp_path,
            "tsconfig.json",
            json.dumps({"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}),
        )
        result1 = deps_detector_mod._load_tsconfig_paths(tmp_path)
        result2 = deps_detector_mod._load_tsconfig_paths(tmp_path)
        assert result1 is result2  # same dict object from cache

    def test_multiple_targets_uses_first(self, tmp_path):
        """When an alias has multiple targets, use the first (TS behavior)."""
        _write(
            tmp_path,
            "tsconfig.json",
            json.dumps({"compilerOptions": {"paths": {"@/*": ["./src/*", "./lib/*"]}}}),
        )
        paths = deps_detector_mod._load_tsconfig_paths(tmp_path)
        assert paths["@/"] == "src/"

    def test_extends_npm_package_skipped(self, tmp_path):
        """extends pointing to an npm package (starts with @) is skipped."""
        _write(
            tmp_path,
            "tsconfig.json",
            json.dumps(
                {"extends": "@tsconfig/node20/tsconfig.json", "compilerOptions": {}}
            ),
        )
        paths = deps_detector_mod._load_tsconfig_paths(tmp_path)
        assert paths == {"@/": "src/"}


# ── Framework file support ──────────────────────────────────────


class TestFrameworkFiles:
    def test_svelte_import_creates_graph_edge(self, tmp_path):
        """.svelte file importing .ts creates a graph edge."""

        _write(tmp_path, "utils.ts", "export function foo() { return 1; }\n")
        _write(
            tmp_path,
            "App.svelte",
            ("<script>\nimport { foo } from './utils';\n</script>\n<p>{foo()}</p>\n"),
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        utils_key = str((tmp_path / "utils.ts").resolve())
        svelte_key = str((tmp_path / "App.svelte").resolve())
        assert svelte_key in graph[utils_key]["importers"]
        assert utils_key in graph[svelte_key]["imports"]

    def test_vue_import_creates_graph_edge(self, tmp_path):
        """.vue file importing .ts creates a graph edge."""

        _write(tmp_path, "api.ts", "export const fetchData = () => {};\n")
        _write(
            tmp_path,
            "App.vue",
            (
                '<script setup lang="ts">\n'
                "import { fetchData } from './api';\n"
                "</script>\n"
                "<template><div /></template>\n"
            ),
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        api_key = str((tmp_path / "api.ts").resolve())
        vue_key = str((tmp_path / "App.vue").resolve())
        assert vue_key in graph[api_key]["importers"]

    def test_astro_import_creates_graph_edge(self, tmp_path):
        """.astro frontmatter imports create graph edges."""

        _write(tmp_path, "config.ts", "export const siteTitle = 'My Site';\n")
        _write(
            tmp_path,
            "Layout.astro",
            (
                "---\n"
                "import { siteTitle } from './config';\n"
                "---\n"
                "<html><head><title>{siteTitle}</title></head></html>\n"
            ),
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        config_key = str((tmp_path / "config.ts").resolve())
        astro_key = str((tmp_path / "Layout.astro").resolve())
        assert astro_key in graph[config_key]["importers"]

    def test_framework_file_does_not_appear_orphaned(self, tmp_path):
        """Framework file nodes are excluded from orphan check (extensions filter)."""

        _write(tmp_path, "utils.ts", "export function foo() { return 1; }\n")
        _write(
            tmp_path,
            "App.svelte",
            ("<script>\nimport { foo } from './utils';\n</script>\n"),
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        orphans, _ = orphaned_detector_mod.detect_orphaned_files(
            tmp_path,
            graph,
            extensions=[".ts", ".tsx"],
            options=orphaned_detector_mod.OrphanedDetectionOptions(
                extra_entry_patterns=[],
                extra_barrel_names=set(),
            ),
        )
        # The .svelte file should not appear in orphans (filtered by extensions)
        orphan_files = {e["file"] for e in orphans}
        svelte_key = str((tmp_path / "App.svelte").resolve())
        assert svelte_key not in orphan_files

    def test_dead_export_not_flagged_when_svelte_uses_it(self, tmp_path):
        """Export used in .svelte file is not flagged as dead."""

        _write(tmp_path, "src/utils.ts", "export function doStuff() { return 1; }\n")
        _write(
            tmp_path,
            "src/App.svelte",
            ("<script>\nimport { doStuff } from './utils';\ndoStuff();\n</script>\n"),
        )

        # _build_reference_index searches SRC_PATH
        refs = _build_reference_index(utils_mod.SRC_PATH, {"doStuff"})
        assert "doStuff" in refs
        assert len(refs["doStuff"]) >= 2  # found in both utils.ts and App.svelte

    def test_framework_with_tsconfig_alias(self, tmp_path):
        """.svelte importing via @/ alias resolves correctly in graph."""

        _write(
            tmp_path,
            "tsconfig.json",
            json.dumps({"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}),
        )
        _write(tmp_path, "src/store.ts", "export const count = 0;\n")
        _write(
            tmp_path,
            "src/Counter.svelte",
            ("<script>\nimport { count } from '@/store';\n</script>\n<p>{count}</p>\n"),
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        store_key = str((tmp_path / "src/store.ts").resolve())
        svelte_key = str((tmp_path / "src/Counter.svelte").resolve())
        assert svelte_key in graph[store_key]["importers"]

    def test_no_framework_files_no_change(self, tmp_path):
        """Projects without framework files produce identical results."""

        _write(tmp_path, "a.ts", "export const x = 1;\n")
        _write(tmp_path, "b.ts", "import { x } from './a';\n")

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        a_key = str((tmp_path / "a.ts").resolve())
        b_key = str((tmp_path / "b.ts").resolve())
        assert len(graph) == 2
        assert a_key in graph[b_key]["imports"]

    def test_framework_html_false_match_ignored(self, tmp_path):
        """HTML attribute that happens to match import pattern is harmless.

        If a template contains `from "..."` in a non-import context,
        the resolved path won't exist → silently dropped.
        """

        _write(tmp_path, "utils.ts", "export const x = 1;\n")
        _write(
            tmp_path,
            "App.svelte",
            (
                "<script>\nimport { x } from './utils';\n</script>\n"
                '<img alt="sent from &quot;Bob&quot;" />\n'
            ),
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        # Only the real import creates an edge, the img attr doesn't
        svelte_key = str((tmp_path / "App.svelte").resolve())
        assert graph[svelte_key]["import_count"] == 1
