"""Tests for framework-owned entry points in the orphaned-file detector.

Every rule here states the same product claim from a different angle: a file a
file-based router loads by path is not dead code, and a file nothing reaches is
still reported.
"""

from __future__ import annotations

import json
from pathlib import Path

from desloppify.engine.detectors.orphaned import (
    OrphanedDetectionOptions,
    detect_orphaned_files,
)
from desloppify.engine.detectors.orphaned_frameworks import (
    build_framework_context,
    detect_nuxt,
    is_tooling_config,
    package_script_entries,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(root: Path, rel_path: str, lines: int = 20) -> Path:
    """Write a dummy source file of *lines* lines and return its path."""
    target = root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(f"line {i}" for i in range(lines)))
    return target


def _package_json(root: Path, **sections) -> None:
    """Write a package.json with the given top-level sections."""
    (root / "package.json").write_text(json.dumps(sections))


def _nuxt4_project(root: Path) -> None:
    """Lay out a minimal Nuxt 4 project: nuxt.config + app/ srcDir + server/."""
    (root / "nuxt.config.ts").write_text(
        "export default defineNuxtConfig({\n"
        "  imports: { dirs: ['composables/**'] },\n"
        "})\n"
    )
    _package_json(root, dependencies={"nuxt": "^4.5.0"})
    (root / "app").mkdir(exist_ok=True)


def _orphans(root: Path, files: list[Path]) -> set[str]:
    """Run the detector over *files*, all with zero importers, and return the hits."""
    graph = {
        str(f): {"imports": set(), "importer_count": 0, "importers": []} for f in files
    }
    entries, _total = detect_orphaned_files(root, graph, [".ts", ".vue"])
    return {str(Path(e["file"]).relative_to(root)) for e in entries}


# ===================================================================
# Nuxt / Nitro
# ===================================================================


class TestNuxtEntryPoints:
    """A Nuxt project's routed, registered and auto-imported files are entries."""

    def test_nitro_api_route_is_not_orphaned(self, tmp_path):
        """A server/api handler is loaded by path, so zero importers is normal."""
        _nuxt4_project(tmp_path)
        handler = _write(tmp_path, "server/api/puzzle/[id]/submit.post.ts", lines=40)

        assert _orphans(tmp_path, [handler]) == set()

    def test_every_nitro_directory_is_an_entry_point(self, tmp_path):
        """Nitro loads routes, plugins, middleware and tasks by location."""
        _nuxt4_project(tmp_path)
        files = [
            _write(tmp_path, "server/routes/health.ts"),
            _write(tmp_path, "server/plugins/pack-sync.ts"),
            _write(tmp_path, "server/middleware/auth.ts"),
            _write(tmp_path, "server/tasks/daily/generate.ts"),
        ]

        assert _orphans(tmp_path, files) == set()

    def test_auto_imported_app_directories_are_entry_points(self, tmp_path):
        """Components, composables, layouts, pages and plugins auto-register."""
        _nuxt4_project(tmp_path)
        files = [
            _write(tmp_path, "app/components/daily/DailyGame.vue"),
            _write(tmp_path, "app/composables/useLeaderboard.ts"),
            _write(tmp_path, "app/layouts/default.vue"),
            _write(tmp_path, "app/pages/index.vue"),
            _write(tmp_path, "app/plugins/posthog.client.ts"),
            _write(tmp_path, "app/middleware/admin.ts"),
            _write(tmp_path, "app/utils/format-duration.ts"),
        ]

        assert _orphans(tmp_path, files) == set()

    def test_app_and_error_roots_are_entry_points(self, tmp_path):
        """app.vue and error.vue are the application shell, not dead files."""
        _nuxt4_project(tmp_path)
        files = [_write(tmp_path, "app/app.vue"), _write(tmp_path, "app/error.vue")]

        assert _orphans(tmp_path, files) == set()

    def test_unreferenced_library_module_is_still_reported(self, tmp_path):
        """A lib module nothing imports is dead code, Nuxt project or not."""
        _nuxt4_project(tmp_path)
        dead = _write(tmp_path, "server/lib/crossword/abandoned-grader.ts", lines=40)

        assert _orphans(tmp_path, [dead]) == {"server/lib/crossword/abandoned-grader.ts"}

    def test_lookalike_directory_outside_a_nuxt_project_is_reported(self, tmp_path):
        """server/api/ only means something when a Nuxt project claims it."""
        _package_json(tmp_path, dependencies={"express": "^4.0.0"})
        handler = _write(tmp_path, "server/api/thing.post.ts", lines=40)

        assert _orphans(tmp_path, [handler]) == {"server/api/thing.post.ts"}

    def test_custom_imports_dirs_are_honored(self, tmp_path):
        """A directory listed in nuxt.config imports.dirs is auto-imported."""
        (tmp_path / "nuxt.config.ts").write_text(
            "export default defineNuxtConfig({\n"
            "  imports: { dirs: ['stores/**', '~/helpers'] },\n"
            "})\n"
        )
        _package_json(tmp_path, dependencies={"nuxt": "^4.5.0"})
        (tmp_path / "app").mkdir()
        files = [
            _write(tmp_path, "app/stores/user.ts"),
            _write(tmp_path, "app/helpers/dates.ts"),
        ]

        assert _orphans(tmp_path, files) == set()

    def test_nuxt3_layout_keeps_app_directories_at_the_root(self, tmp_path):
        """Without an app/ srcDir, pages and components live at the project root."""
        (tmp_path / "nuxt.config.ts").write_text("export default defineNuxtConfig({})\n")
        _package_json(tmp_path, dependencies={"nuxt": "^3.14.0"})
        (tmp_path / "pages").mkdir()
        files = [
            _write(tmp_path, "pages/index.vue"),
            _write(tmp_path, "components/Board.vue"),
            _write(tmp_path, "server/api/today.get.ts"),
        ]

        assert _orphans(tmp_path, files) == set()

    def test_explicit_src_dir_moves_the_app_directories(self, tmp_path):
        """srcDir in nuxt.config decides where pages and components are read from."""
        (tmp_path / "nuxt.config.ts").write_text(
            "export default defineNuxtConfig({ srcDir: 'client/' })\n"
        )
        _package_json(tmp_path, dependencies={"nuxt": "^3.14.0"})
        routed = _write(tmp_path, "client/pages/index.vue")
        elsewhere = _write(tmp_path, "other/pages/index.vue", lines=30)

        assert _orphans(tmp_path, [routed, elsewhere]) == {"other/pages/index.vue"}

    def test_detection_falls_back_to_the_package_manifest(self, tmp_path):
        """A nuxt dependency identifies the project when the config is elsewhere."""
        _package_json(tmp_path, devDependencies={"nuxt": "^4.5.0"})
        (tmp_path / "app").mkdir()

        found = detect_nuxt(tmp_path)

        assert found is not None
        assert "server/api" in found.dir_prefixes
        assert "app/components" in found.dir_prefixes

    def test_no_nuxt_no_rules(self, tmp_path):
        """A project with no Nuxt signal contributes no Nuxt entry points."""
        _package_json(tmp_path, dependencies={"react": "^18.0.0"})

        assert detect_nuxt(tmp_path) is None


# ===================================================================
# Other file-based routers
# ===================================================================


class TestOtherFrameworks:
    """The same rule generalises to the other routers desloppify supports."""

    def test_sveltekit_route_files_are_entry_points(self, tmp_path):
        """SvelteKit routes +page/+server by filename prefix."""
        _package_json(tmp_path, devDependencies={"@sveltejs/kit": "^2.0.0"})
        files = [
            _write(tmp_path, "src/routes/blog/+page.svelte"),
            _write(tmp_path, "src/routes/api/+server.ts"),
            _write(tmp_path, "src/hooks.server.ts"),
        ]

        assert _orphans(tmp_path, files) == set()

    def test_sveltekit_colocated_component_is_still_reported(self, tmp_path):
        """A component beside a route has no + prefix, so it must be imported."""
        _package_json(tmp_path, devDependencies={"@sveltejs/kit": "^2.0.0"})
        helper = _write(tmp_path, "src/routes/blog/Sidebar.svelte", lines=30)

        assert _orphans(tmp_path, [helper]) == {"src/routes/blog/Sidebar.svelte"}

    def test_remix_route_modules_are_entry_points(self, tmp_path):
        """Remix loads app/routes and the entry/root modules by convention."""
        _package_json(tmp_path, dependencies={"@remix-run/react": "^2.0.0"})
        files = [
            _write(tmp_path, "app/routes/_index.tsx"),
            _write(tmp_path, "app/root.tsx"),
            _write(tmp_path, "app/entry.server.tsx"),
        ]

        assert _orphans(tmp_path, files) == set()

    def test_astro_pages_are_entry_points(self, tmp_path):
        """Astro routes everything under src/pages."""
        (tmp_path / "astro.config.mjs").write_text("export default {}\n")
        _package_json(tmp_path, dependencies={"astro": "^4.0.0"})
        files = [
            _write(tmp_path, "src/pages/index.astro"),
            _write(tmp_path, "src/middleware.ts"),
        ]

        assert _orphans(tmp_path, files) == set()

    def test_nextjs_app_router_conventions_survive_the_refactor(self, tmp_path):
        """page/layout/route inside app/ stay entry points, as before."""
        (tmp_path / "next.config.js").write_text("module.exports = {}\n")
        _package_json(tmp_path, dependencies={"next": "^15.0.0"})
        files = [
            _write(tmp_path, "app/dashboard/page.tsx"),
            _write(tmp_path, "app/dashboard/layout.tsx"),
            _write(tmp_path, "app/api/hook/route.ts"),
            _write(tmp_path, "middleware.ts"),
        ]

        assert _orphans(tmp_path, files) == set()


# ===================================================================
# Entry points that belong to no framework
# ===================================================================


class TestToolingAndScriptEntries:
    """Config files and package scripts reach code the import graph cannot see."""

    def test_top_level_tool_config_is_not_orphaned(self, tmp_path):
        """A CLI loads its own *.config.* file; nothing imports it."""
        _package_json(tmp_path, dependencies={"vitest": "^3.0.0"})
        files = [
            _write(tmp_path, "vitest.config.ts"),
            _write(tmp_path, "playwright.config.ts"),
            _write(tmp_path, "drizzle.config.ts"),
        ]

        assert _orphans(tmp_path, files) == set()

    def test_nested_config_lookalike_is_still_reported(self, tmp_path):
        """Only a top-level config is tool-loaded; a nested one is ordinary code."""
        _package_json(tmp_path, dependencies={"vitest": "^3.0.0"})
        nested = _write(tmp_path, "src/feature/feature.config.ts", lines=30)

        assert _orphans(tmp_path, [nested]) == {"src/feature/feature.config.ts"}

    def test_is_tooling_config_rejects_a_plain_module(self):
        """A top-level module that is not a *.config.* file gets no exemption."""
        assert is_tooling_config("vitest.config.ts") is True
        assert is_tooling_config("helpers.ts") is False
        assert is_tooling_config("app/vitest.config.ts") is False

    def test_file_invoked_by_a_package_script_is_not_orphaned(self, tmp_path):
        """`tsx server/db/seed.ts` makes that file reachable."""
        _package_json(
            tmp_path,
            scripts={"db:seed": "tsx server/db/seed.ts", "lint": "eslint ."},
        )
        seed = _write(tmp_path, "server/db/seed.ts", lines=40)
        unused = _write(tmp_path, "server/db/leftover.ts", lines=40)

        assert _orphans(tmp_path, [seed, unused]) == {"server/db/leftover.ts"}

    def test_package_script_entries_ignores_paths_that_do_not_exist(self, tmp_path):
        """A script naming a missing file contributes nothing."""
        _package_json(tmp_path, scripts={"build": "tsx scripts/ghost.ts"})

        assert package_script_entries(tmp_path) == frozenset()

    def test_react_email_templates_are_discovered_by_folder(self, tmp_path):
        """react-email renders whatever sits in emails/, imported or not."""
        _package_json(tmp_path, devDependencies={"react-email": "^6.9.0"})
        template = _write(tmp_path, "emails/MagicLink.tsx", lines=40)

        assert _orphans(tmp_path, [template]) == set()


# ===================================================================
# Opting out
# ===================================================================


class TestFrameworkDetectionCanBeDisabled:
    """detect_frameworks=False restores the plain graph check."""

    def test_disabled_detection_reports_framework_entry_points(self, tmp_path):
        """With the flag off, a Nitro handler is judged on importers alone."""
        _nuxt4_project(tmp_path)
        handler = _write(tmp_path, "server/api/today.get.ts", lines=40)
        graph = {
            str(handler): {"imports": set(), "importer_count": 0, "importers": []}
        }

        entries, _total = detect_orphaned_files(
            tmp_path,
            graph,
            [".ts"],
            options=OrphanedDetectionOptions(detect_frameworks=False),
        )

        assert [e["file"] for e in entries] == [str(handler)]


class TestFrameworkContext:
    """The context reports which frameworks it recognised."""

    def test_a_nuxt_project_with_react_email_reports_both(self, tmp_path):
        """Frameworks stack: each contributes its own entry points."""
        _nuxt4_project(tmp_path)
        _package_json(
            tmp_path,
            dependencies={"nuxt": "^4.5.0"},
            devDependencies={"react-email": "^6.9.0"},
        )

        context = build_framework_context(tmp_path)

        assert {fw.name for fw in context.frameworks} == {"nuxt", "react-email"}

    def test_a_plain_typescript_project_detects_nothing(self, tmp_path):
        """No framework, no manifest scripts: the context is empty."""
        _package_json(tmp_path, dependencies={"lodash": "^4.0.0"})

        context = build_framework_context(tmp_path)

        assert context.frameworks == []
        assert context.script_entries == frozenset()
