"""Tests for Nuxt/Nitro conventions and auto-imports in orphaned detection."""

from __future__ import annotations

from pathlib import Path

from desloppify.engine.detectors._orphaned.nuxt import (
    _component_names,
    build_nuxt_usage_index,
    detect_nuxt_project,
    is_nuxt_convention_entry,
    nuxt_auto_import_names,
)
from desloppify.engine.detectors.orphaned import (
    OrphanedDetectionOptions,
    detect_orphaned_files,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _graph_entry(*, importer_count: int = 0) -> dict:
    """Build a minimal graph node dict."""
    return {"imports": set(), "importer_count": importer_count, "importers": []}


def _write(path: Path, body: str = "", lines: int = 20) -> Path:
    """Write a file padded to *lines* so it clears the size floor."""
    path.parent.mkdir(parents=True, exist_ok=True)
    padding = "\n".join(f"// line {i}" for i in range(lines))
    path.write_text(f"{body}\n{padding}\n")
    return path


def _nuxt_root(root: Path) -> Path:
    """Make *root* look like a Nuxt project."""
    (root / "nuxt.config.ts").write_text("export default defineNuxtConfig({})")
    return root


# ===================================================================
# detect_nuxt_project
# ===================================================================


class TestDetectNuxtProject:
    """A project counts as Nuxt via its config file or its manifest."""

    def test_nuxt_config_ts_detected(self, tmp_path):
        (tmp_path / "nuxt.config.ts").write_text("export default {}")
        assert detect_nuxt_project(tmp_path) is True

    def test_nuxt_config_mjs_detected(self, tmp_path):
        (tmp_path / "nuxt.config.mjs").write_text("export default {}")
        assert detect_nuxt_project(tmp_path) is True

    def test_package_json_dependency_detected(self, tmp_path):
        (tmp_path / "package.json").write_text('{"dependencies": {"nuxt": "^4.0.0"}}')
        assert detect_nuxt_project(tmp_path) is True

    def test_dev_dependency_detected(self, tmp_path):
        (tmp_path / "package.json").write_text('{"devDependencies": {"nuxt": "^3.0.0"}}')
        assert detect_nuxt_project(tmp_path) is True

    def test_plain_project_not_detected(self, tmp_path):
        (tmp_path / "package.json").write_text('{"dependencies": {"react": "^18.0.0"}}')
        assert detect_nuxt_project(tmp_path) is False

    def test_unreadable_manifest_not_detected(self, tmp_path):
        (tmp_path / "package.json").write_text("not json at all")
        assert detect_nuxt_project(tmp_path) is False


# ===================================================================
# is_nuxt_convention_entry
# ===================================================================


class TestNuxtConventionEntry:
    """File-routed and auto-registered trees are entry points."""

    def test_nitro_api_route(self):
        assert is_nuxt_convention_entry("server/api/puzzle/today.get.ts") is True

    def test_nitro_non_api_route(self):
        assert is_nuxt_convention_entry("server/routes/pricing.get.ts") is True

    def test_nitro_middleware(self):
        assert is_nuxt_convention_entry("server/middleware/auth.ts") is True

    def test_nitro_plugin(self):
        assert is_nuxt_convention_entry("server/plugins/pack-sync.ts") is True

    def test_nitro_scheduled_task(self):
        assert is_nuxt_convention_entry("server/tasks/daily/generate.ts") is True

    def test_server_lib_is_not_an_entry(self):
        """server/lib holds ordinary modules, so it keeps its orphan verdict."""
        assert is_nuxt_convention_entry("server/lib/entitlement.ts") is False

    def test_nuxt4_pages_under_srcdir(self):
        assert is_nuxt_convention_entry("app/pages/index.vue") is True

    def test_nuxt3_pages_at_root(self):
        assert is_nuxt_convention_entry("pages/index.vue") is True

    def test_layouts_middleware_and_plugins(self):
        assert is_nuxt_convention_entry("app/layouts/default.vue") is True
        assert is_nuxt_convention_entry("app/middleware/admin.ts") is True
        assert is_nuxt_convention_entry("app/plugins/posthog.client.ts") is True

    def test_root_configs(self):
        assert is_nuxt_convention_entry("nuxt.config.ts") is True
        assert is_nuxt_convention_entry("capacitor.config.ts") is True

    def test_root_app_and_error_shells(self):
        assert is_nuxt_convention_entry("app/app.vue") is True
        assert is_nuxt_convention_entry("app.vue") is True
        assert is_nuxt_convention_entry("app/error.vue") is True

    def test_unrelated_root_config_is_not_an_entry(self):
        assert is_nuxt_convention_entry("vitest.config.ts") is False

    def test_components_are_not_convention_entries(self):
        """Components are resolved by usage, not exempted by location."""
        assert is_nuxt_convention_entry("app/components/game/GameOutcome.vue") is False


# ===================================================================
# Auto-import naming
# ===================================================================


class TestComponentNames:
    """Nuxt derives a component's name from its path plus its filename."""

    def test_directory_prefix_deduplicated(self):
        assert "GameOutcomeDrawer" in _component_names(("game",), "GameOutcomeDrawer")

    def test_directory_prefix_applied_when_not_repeated(self):
        assert "AccountThemeSwitcher" in _component_names(("account",), "ThemeSwitcher")

    def test_nested_directories_join(self):
        assert "UiButton" in _component_names(("ui", "button"), "Button")

    def test_index_takes_its_directory_name(self):
        assert "Roster" in _component_names(("roster",), "index")

    def test_flat_component_keeps_its_stem(self):
        assert _component_names((), "Board") == {"Board"}

    def test_bare_filename_is_always_a_candidate(self):
        """pathPrefix: false, and path imports, both register the bare stem."""
        assert "ThemeSwitcher" in _component_names(("account",), "ThemeSwitcher")


class TestAutoImportSurface:
    """Only auto-imported directories resolve by name."""

    def test_component_resolves_to_registered_name(self, tmp_path):
        path = _write(tmp_path / "app/components/game/GameOutcomeDrawer.vue")
        names = nuxt_auto_import_names("app/components/game/GameOutcomeDrawer.vue", str(path))
        assert names is not None
        assert "GameOutcomeDrawer" in names

    def test_mode_suffix_stripped(self, tmp_path):
        path = _write(tmp_path / "app/components/badge/BadgeIcon.client.vue")
        names = nuxt_auto_import_names("app/components/badge/BadgeIcon.client.vue", str(path))
        assert names is not None
        assert "BadgeIcon" in names

    def test_composable_resolves_to_its_exports(self, tmp_path):
        path = _write(
            tmp_path / "app/composables/useUser.ts",
            body="export function useUser() { return null }",
        )
        names = nuxt_auto_import_names("app/composables/useUser.ts", str(path))
        assert names is not None
        assert "useUser" in names

    def test_shared_module_resolves_to_its_exports(self, tmp_path):
        path = _write(
            tmp_path / "shared/types/crossword.ts",
            body="export interface CrosswordPublic { id: string }",
        )
        names = nuxt_auto_import_names("shared/types/crossword.ts", str(path))
        assert names is not None
        assert "CrosswordPublic" in names

    def test_export_list_names_collected(self, tmp_path):
        path = _write(
            tmp_path / "shared/utils/ban.ts",
            body="const isScoreBanActive = () => true\nexport { isScoreBanActive }",
        )
        names = nuxt_auto_import_names("shared/utils/ban.ts", str(path))
        assert names is not None
        assert "isScoreBanActive" in names

    def test_non_auto_imported_directory_returns_none(self, tmp_path):
        path = _write(tmp_path / "server/lib/entitlement.ts")
        assert nuxt_auto_import_names("server/lib/entitlement.ts", str(path)) is None


# ===================================================================
# Usage index
# ===================================================================


class TestUsageIndex:
    """Template tags and bare identifiers both count as references."""

    def test_pascal_case_tag_is_a_reference(self, set_project_root):
        root = set_project_root
        _write(root / "app/pages/index.vue", body="<template><GameOutcome /></template>")
        index = build_nuxt_usage_index(root)
        assert index.is_used_outside({"GameOutcome"}, "/elsewhere/GameOutcome.vue") is True

    def test_kebab_case_tag_resolves_to_the_registered_name(self, set_project_root):
        root = set_project_root
        _write(
            root / "app/pages/index.vue",
            body="<template><game-outcome-drawer /></template>",
        )
        index = build_nuxt_usage_index(root)
        assert index.is_used_outside({"GameOutcomeDrawer"}, "/elsewhere/x.vue") is True

    def test_a_files_own_mention_is_not_a_reference(self, set_project_root):
        root = set_project_root
        lonely = _write(root / "app/composables/useLonely.ts", body="export function useLonely() {}")
        index = build_nuxt_usage_index(root)
        assert index.is_used_outside({"useLonely"}, str(lonely.resolve())) is False

    def test_unreferenced_name_is_not_used(self, set_project_root):
        root = set_project_root
        _write(root / "app/pages/index.vue", body="<template><div /></template>")
        index = build_nuxt_usage_index(root)
        assert index.is_used_outside({"NeverMentioned"}, "/elsewhere/x.vue") is False


# ===================================================================
# detect_orphaned_files integration
# ===================================================================


class TestNuxtIntegration:
    """End-to-end orphan verdicts on a Nuxt-shaped tree."""

    def test_convention_files_are_not_orphaned(self, set_project_root):
        root = _nuxt_root(set_project_root)
        route = _write(root / "server/api/puzzle/today.get.ts")
        task = _write(root / "server/tasks/daily/generate.ts")
        page = _write(root / "app/pages/index.vue")
        plugin = _write(root / "app/plugins/posthog.client.ts")
        stray = _write(root / "server/lib/unused-helper.ts")

        graph = {
            str(p): _graph_entry() for p in (route, task, page, plugin, stray)
        }
        entries, total = detect_orphaned_files(root, graph, [".ts", ".vue"])

        assert total == 5
        assert [e["file"] for e in entries] == [str(stray)]

    def test_component_used_in_a_template_is_not_orphaned(self, set_project_root):
        root = _nuxt_root(set_project_root)
        used = _write(root / "app/components/game/GameOutcomeDrawer.vue")
        unused = _write(root / "app/components/game/GameGhostPanel.vue")
        _write(
            root / "app/pages/index.vue",
            body="<template><GameOutcomeDrawer /></template>",
        )

        graph = {str(used): _graph_entry(), str(unused): _graph_entry()}
        entries, _total = detect_orphaned_files(root, graph, [".ts", ".vue"])

        assert [e["file"] for e in entries] == [str(unused)]

    def test_prefixed_component_resolves_through_its_registered_name(self, set_project_root):
        root = _nuxt_root(set_project_root)
        switcher = _write(root / "app/components/account/ThemeSwitcher.vue")
        _write(
            root / "app/pages/account.vue",
            body="<template><AccountThemeSwitcher /></template>",
        )

        graph = {str(switcher): _graph_entry()}
        entries, _total = detect_orphaned_files(root, graph, [".ts", ".vue"])

        assert entries == []

    def test_component_referenced_by_its_bare_filename_is_not_orphaned(self, set_project_root):
        """A path import gives the consumer the bare stem as its local tag."""
        root = _nuxt_root(set_project_root)
        premium = _write(root / "app/components/layout/PremiumBanner.vue")
        _write(root / "app/layouts/default.vue", body="<template><PremiumBanner /></template>")

        graph = {str(premium): _graph_entry()}
        entries, _total = detect_orphaned_files(root, graph, [".ts", ".vue"])

        assert entries == []

    def test_composable_called_without_an_import_is_not_orphaned(self, set_project_root):
        root = _nuxt_root(set_project_root)
        composable = _write(
            root / "app/composables/useUser.ts",
            body="export function useUser() { return null }",
        )
        _write(
            root / "app/pages/index.vue",
            body="<script setup>const user = useUser()</script>",
        )

        graph = {str(composable): _graph_entry()}
        entries, _total = detect_orphaned_files(root, graph, [".ts", ".vue"])

        assert entries == []

    def test_unreferenced_composable_is_still_orphaned(self, set_project_root):
        root = _nuxt_root(set_project_root)
        composable = _write(
            root / "app/composables/useForgotten.ts",
            body="export function useForgotten() { return null }",
        )

        graph = {str(composable): _graph_entry()}
        entries, _total = detect_orphaned_files(root, graph, [".ts", ".vue"])

        assert [e["file"] for e in entries] == [str(composable)]

    def test_non_nuxt_project_keeps_reporting_those_paths(self, set_project_root):
        root = set_project_root
        route = _write(root / "server/api/puzzle/today.get.ts")

        graph = {str(route): _graph_entry()}
        entries, _total = detect_orphaned_files(root, graph, [".ts"])

        assert [e["file"] for e in entries] == [str(route)]

    def test_detect_frameworks_false_disables_nuxt_rules(self, set_project_root):
        root = _nuxt_root(set_project_root)
        page = _write(root / "app/pages/index.vue")

        graph = {str(page): _graph_entry()}
        entries, _total = detect_orphaned_files(
            root,
            graph,
            [".vue"],
            options=OrphanedDetectionOptions(detect_frameworks=False),
        )

        assert [e["file"] for e in entries] == [str(page)]
