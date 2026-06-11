"""Tests for desloppify.engine.detectors.orphaned — orphaned file detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from desloppify.engine.detectors.orphaned import (
    OrphanedDetectionOptions,
    _detect_nextjs_project,
    _has_dunder_all,
    _is_dynamically_imported,
    _is_nextjs_convention_entry,
    detect_orphaned_files,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _graph_entry(
    *,
    imports: set[str] | None = None,
    importer_count: int = 0,
    importers: list[str] | None = None,
) -> dict:
    """Build a minimal graph node dict."""
    return {
        "imports": imports or set(),
        "importer_count": importer_count,
        "importers": importers or [],
    }


def _write_file(path: Path, lines: int = 20) -> Path:
    """Write a dummy file with the given number of lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"line {i}" for i in range(lines)))
    return path


# ===================================================================
# _is_dynamically_imported
# ===================================================================


class TestIsDynamicallyImported:
    """Unit tests for the _is_dynamically_imported helper."""

    @patch("desloppify.engine.detectors.orphaned.rel")
    def test_direct_relative_path_match(self, mock_rel):
        """File matches when its relative path (no ext) equals the target."""
        filepath = "/project/src/utils/helpers.ts"
        mock_rel.return_value = "src/utils/helpers.ts"
        targets = {"src/utils/helpers"}
        assert _is_dynamically_imported(filepath, targets) is True

    @patch("desloppify.engine.detectors.orphaned.rel")
    def test_stem_match(self, mock_rel):
        """File matches when its stem equals the target."""
        filepath = "/project/src/config.ts"
        mock_rel.return_value = "src/config.ts"
        targets = {"config"}
        assert _is_dynamically_imported(filepath, targets) is True

    @patch("desloppify.engine.detectors.orphaned.rel")
    def test_target_with_leading_dot_slash(self, mock_rel):
        """Leading ./ is stripped from targets before matching."""
        filepath = "/project/src/foo.ts"
        mock_rel.return_value = "src/foo.ts"
        targets = {"./src/foo"}
        assert _is_dynamically_imported(filepath, targets) is True

    @patch("desloppify.engine.detectors.orphaned.rel")
    def test_with_alias_resolver(self, mock_rel):
        """Alias resolver transforms the target before matching."""
        filepath = "/project/src/utils/helpers.ts"
        mock_rel.return_value = "src/utils/helpers.ts"
        targets = {"@/utils/helpers"}

        def resolver(t: str) -> str:
            return t.replace("@/", "src/")

        assert (
            _is_dynamically_imported(filepath, targets, alias_resolver=resolver) is True
        )

    @patch("desloppify.engine.detectors.orphaned.rel")
    def test_no_match_returns_false(self, mock_rel):
        """Returns False when no target matches."""
        filepath = "/project/src/utils/helpers.ts"
        mock_rel.return_value = "src/utils/helpers.ts"
        targets = {"totally/different", "unrelated"}
        assert _is_dynamically_imported(filepath, targets) is False

    @patch("desloppify.engine.detectors.orphaned.rel")
    def test_empty_targets_returns_false(self, mock_rel):
        """Returns False when the target set is empty."""
        filepath = "/project/src/utils/helpers.ts"
        mock_rel.return_value = "src/utils/helpers.ts"
        assert _is_dynamically_imported(filepath, set()) is False

    @patch("desloppify.engine.detectors.orphaned.rel")
    def test_basename_match_via_trailing_slash(self, mock_rel):
        """Matches target ending with /filename."""
        filepath = "/project/src/deep/nested/widget.ts"
        mock_rel.return_value = "src/deep/nested/widget.ts"
        targets = {"components/widget"}
        # stem "widget" == target ending "widget" after split
        assert _is_dynamically_imported(filepath, targets) is True

    @patch("desloppify.engine.detectors.orphaned.rel")
    def test_full_filename_match(self, mock_rel):
        """Matches when target ends with /filename.ext."""
        filepath = "/project/src/utils/helpers.ts"
        mock_rel.return_value = "src/utils/helpers.ts"
        targets = {"stuff/helpers.ts"}
        assert _is_dynamically_imported(filepath, targets) is True


# ===================================================================
# detect_orphaned_files
# ===================================================================


class TestDetectOrphanedFiles:
    """Integration tests for detect_orphaned_files using tmp_path."""

    def test_files_with_importers_not_orphaned(self, tmp_path):
        """Files with importer_count > 0 should not appear in results."""
        f1 = _write_file(tmp_path / "used.py", lines=50)
        f2 = _write_file(tmp_path / "unused.py", lines=50)

        graph = {
            str(f1): _graph_entry(importer_count=3, importers=["a", "b", "c"]),
            str(f2): _graph_entry(importer_count=0),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        assert total == 2
        assert len(entries) == 1
        assert entries[0]["file"] == str(f2)

    def test_entry_pattern_match_excluded(self, tmp_path):
        """Files matching entry_patterns are not reported as orphaned."""
        f1 = _write_file(tmp_path / "main.py", lines=30)
        f2 = _write_file(tmp_path / "app.py", lines=30)
        f3 = _write_file(tmp_path / "orphan.py", lines=30)

        graph = {
            str(f1): _graph_entry(importer_count=0),
            str(f2): _graph_entry(importer_count=0),
            str(f3): _graph_entry(importer_count=0),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(
                tmp_path,
                graph,
                [".py"],
                options=OrphanedDetectionOptions(extra_entry_patterns=["main", "app"]),
            )

        assert total == 3
        assert len(entries) == 1
        assert entries[0]["file"] == str(f3)

    def test_sphinx_conf_py_excluded_by_python_entry_patterns(self, tmp_path):
        """A Sphinx ``docs/conf.py`` is an entry point, not an orphan.

        Regression for PY_ENTRY_PATTERNS: ``conf.py`` is loaded by ``sphinx-build``
        and has zero importers by design, so it must be recognized as an entry
        point rather than flagged as a dead file.
        """
        from desloppify.languages.python.phases import PY_ENTRY_PATTERNS

        conf = _write_file(tmp_path / "docs" / "conf.py", lines=30)
        orphan = _write_file(tmp_path / "dead.py", lines=30)
        graph = {
            str(conf): _graph_entry(importer_count=0),
            str(orphan): _graph_entry(importer_count=0),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(
                tmp_path,
                graph,
                [".py"],
                options=OrphanedDetectionOptions(
                    extra_entry_patterns=PY_ENTRY_PATTERNS
                ),
            )

        assert total == 2
        assert [e["file"] for e in entries] == [str(orphan)]

    def test_barrel_names_excluded(self, tmp_path):
        """Files matching barrel_names are not reported as orphaned."""
        f1 = _write_file(tmp_path / "index.ts", lines=30)
        f2 = _write_file(tmp_path / "orphan.ts", lines=30)

        graph = {
            str(f1): _graph_entry(importer_count=0),
            str(f2): _graph_entry(importer_count=0),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(
                tmp_path,
                graph,
                [".ts"],
                options=OrphanedDetectionOptions(extra_barrel_names={"index.ts"}),
            )

        assert total == 2
        assert len(entries) == 1
        assert entries[0]["file"] == str(f2)

    def test_small_files_suppressed(self, tmp_path):
        """Files with fewer than 10 lines are suppressed."""
        f_small = _write_file(tmp_path / "tiny.py", lines=5)
        f_big = _write_file(tmp_path / "large.py", lines=50)

        graph = {
            str(f_small): _graph_entry(importer_count=0),
            str(f_big): _graph_entry(importer_count=0),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        assert total == 2
        assert len(entries) == 1
        assert entries[0]["file"] == str(f_big)
        assert entries[0]["loc"] == 50

    def test_dynamically_imported_files_excluded(self, tmp_path):
        """Files found by the dynamic_import_finder are not orphaned."""
        f1 = _write_file(tmp_path / "lazy.py", lines=30)
        f2 = _write_file(tmp_path / "orphan.py", lines=30)

        graph = {
            str(f1): _graph_entry(importer_count=0),
            str(f2): _graph_entry(importer_count=0),
        }

        def mock_dynamic_finder(path, extensions):
            return {"lazy"}

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(
                tmp_path,
                graph,
                [".py"],
                options=OrphanedDetectionOptions(
                    dynamic_import_finder=mock_dynamic_finder
                ),
            )

        assert total == 2
        assert len(entries) == 1
        assert entries[0]["file"] == str(f2)

    def test_results_sorted_by_loc_descending(self, tmp_path):
        """Results are sorted by LOC descending (largest files first)."""
        f_small = _write_file(tmp_path / "small.py", lines=20)
        f_medium = _write_file(tmp_path / "medium.py", lines=50)
        f_large = _write_file(tmp_path / "large.py", lines=100)

        graph = {
            str(f_small): _graph_entry(importer_count=0),
            str(f_medium): _graph_entry(importer_count=0),
            str(f_large): _graph_entry(importer_count=0),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        assert total == 3
        assert len(entries) == 3
        assert entries[0]["loc"] == 100
        assert entries[1]["loc"] == 50
        assert entries[2]["loc"] == 20

    def test_returns_entries_and_total_files(self, tmp_path):
        """Return value is (entries_list, total_files_in_graph)."""
        f1 = _write_file(tmp_path / "a.py", lines=15)
        f2 = _write_file(tmp_path / "b.py", lines=15)
        f3 = _write_file(tmp_path / "c.py", lines=15)

        graph = {
            str(f1): _graph_entry(importer_count=2),
            str(f2): _graph_entry(importer_count=0),
            str(f3): _graph_entry(importer_count=1),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        assert total == 3
        assert len(entries) == 1
        assert entries[0]["file"] == str(f2)

    def test_empty_graph(self, tmp_path):
        """Empty graph returns empty entries and zero total."""
        entries, total = detect_orphaned_files(tmp_path, {}, [".py"])
        assert entries == []
        assert total == 0

    def test_all_files_have_importers(self, tmp_path):
        """When every file is imported, nothing is orphaned."""
        f1 = _write_file(tmp_path / "a.py", lines=50)
        f2 = _write_file(tmp_path / "b.py", lines=50)

        graph = {
            str(f1): _graph_entry(importer_count=1),
            str(f2): _graph_entry(importer_count=5),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        assert entries == []
        assert total == 2

    def test_unreadable_file_treated_as_zero_loc(self, tmp_path):
        """Files that can't be read get loc=0 and are suppressed (< 10)."""
        nonexistent = tmp_path / "ghost.py"

        graph = {
            str(nonexistent): _graph_entry(importer_count=0),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        assert total == 1
        assert entries == []  # suppressed because loc=0 < 10

    def test_dynamic_finder_with_alias_resolver(self, tmp_path):
        """Dynamic import finder + alias resolver together exclude files."""
        f1 = _write_file(tmp_path / "src" / "utils" / "helpers.py", lines=30)

        graph = {
            str(f1): _graph_entry(importer_count=0),
        }

        def mock_dynamic_finder(path, extensions):
            return {"@/utils/helpers"}

        def mock_alias_resolver(target):
            return target.replace("@/", "src/")

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(
                tmp_path,
                graph,
                [".py"],
                options=OrphanedDetectionOptions(
                    dynamic_import_finder=mock_dynamic_finder,
                    alias_resolver=mock_alias_resolver,
                ),
            )

        assert total == 1
        assert entries == []  # excluded by dynamic import with alias resolution

    def test_no_dynamic_finder_skips_check(self, tmp_path):
        """When dynamic_import_finder is None, dynamic check is skipped entirely."""
        f1 = _write_file(tmp_path / "orphan.py", lines=30)

        graph = {
            str(f1): _graph_entry(importer_count=0),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(
                tmp_path,
                graph,
                [".py"],
                options=OrphanedDetectionOptions(dynamic_import_finder=None),
            )

        assert len(entries) == 1
        assert entries[0]["file"] == str(f1)

    def test_entry_has_file_and_loc_keys(self, tmp_path):
        """Each entry includes file/loc plus corroboration metadata."""
        f1 = _write_file(tmp_path / "orphan.py", lines=25)

        graph = {
            str(f1): _graph_entry(importer_count=0),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        assert len(entries) == 1
        assert set(entries[0].keys()) == {"file", "loc", "import_count"}
        assert entries[0]["loc"] == 25
        assert entries[0]["import_count"] == 0

    def test_dunder_all_file_not_orphaned(self, tmp_path):
        """Files defining __all__ are public API surfaces and not orphaned."""
        api_file = tmp_path / "api.py"
        api_file.write_text(
            "__all__ = ['Foo', 'Bar']\n"
            + "\n".join(f"line {i}" for i in range(30))
        )
        orphan_file = _write_file(tmp_path / "orphan.py", lines=30)

        graph = {
            str(api_file): _graph_entry(importer_count=0),
            str(orphan_file): _graph_entry(importer_count=0),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        assert total == 2
        assert len(entries) == 1
        assert entries[0]["file"] == str(orphan_file)

    def test_dunder_all_with_type_annotation(self, tmp_path):
        """Files using ``__all__: list[str] = [...]`` syntax are also excluded."""
        api_file = tmp_path / "api.py"
        api_file.write_text(
            "__all__: list[str] = ['Foo']\n"
            + "\n".join(f"line {i}" for i in range(30))
        )

        graph = {
            str(api_file): _graph_entry(importer_count=0),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        assert total == 1
        assert entries == []

    def test_dunder_all_in_comment_not_excluded(self, tmp_path):
        """A comment mentioning __all__ does not suppress the orphan finding."""
        f = tmp_path / "orphan.py"
        f.write_text(
            "# This file does not define __all__ = [...]\n"
            "x = 1\n" + "\n".join(f"line {i}" for i in range(30))
        )

        graph = {
            str(f): _graph_entry(importer_count=0),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        # The regex requires __all__ at the start of a line, so a comment line
        # starting with # won't match.
        assert len(entries) == 1


# ===================================================================
# _has_dunder_all unit tests
# ===================================================================


class TestHasDunderAll:
    """Unit tests for the _has_dunder_all helper."""

    def test_simple_assignment(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("__all__ = ['foo', 'bar']\n")
        assert _has_dunder_all(str(f)) is True

    def test_type_annotated_assignment(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("__all__: list[str] = ['foo']\n")
        assert _has_dunder_all(str(f)) is True

    def test_no_dunder_all(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("x = 1\ny = 2\n")
        assert _has_dunder_all(str(f)) is False

    def test_dunder_all_in_string(self, tmp_path):
        """__all__ inside a string on its own line still matches (acceptable)."""
        f = tmp_path / "mod.py"
        f.write_text('"""\n__all__ = ["x"]\n"""\n')
        # This is a known acceptable false-negative (would suppress orphan
        # detection), but in practice __all__ in a docstring is extremely rare.
        assert _has_dunder_all(str(f)) is True

    def test_nonexistent_file(self, tmp_path):
        assert _has_dunder_all(str(tmp_path / "nope.py")) is False

    def test_dunder_all_not_at_line_start(self, tmp_path):
        """__all__ preceded by other text on the same line is not matched."""
        f = tmp_path / "mod.py"
        f.write_text("x = __all__\n")
        assert _has_dunder_all(str(f)) is False


# ===================================================================
# Next.js App Router framework awareness
# ===================================================================


class TestDetectNextjsProject:
    """Unit tests for _detect_nextjs_project."""

    def test_next_config_js(self, tmp_path):
        (tmp_path / "next.config.js").write_text("module.exports = {}")
        assert _detect_nextjs_project(tmp_path) is True

    def test_next_config_mjs(self, tmp_path):
        (tmp_path / "next.config.mjs").write_text("export default {}")
        assert _detect_nextjs_project(tmp_path) is True

    def test_next_config_ts(self, tmp_path):
        (tmp_path / "next.config.ts").write_text("export default {}")
        assert _detect_nextjs_project(tmp_path) is True

    def test_no_next_config(self, tmp_path):
        assert _detect_nextjs_project(tmp_path) is False


class TestIsNextjsConventionEntry:
    """Unit tests for _is_nextjs_convention_entry."""

    def test_page_in_app_dir(self):
        assert _is_nextjs_convention_entry("app/dashboard/page.tsx") is True

    def test_layout_in_app_dir(self):
        assert _is_nextjs_convention_entry("app/layout.tsx") is True

    def test_loading_in_nested_app_dir(self):
        assert _is_nextjs_convention_entry("app/shop/items/loading.jsx") is True

    def test_route_handler(self):
        assert _is_nextjs_convention_entry("app/api/users/route.ts") is True

    def test_error_boundary(self):
        assert _is_nextjs_convention_entry("app/error.tsx") is True

    def test_not_found(self):
        assert _is_nextjs_convention_entry("app/not-found.tsx") is True

    def test_global_error(self):
        assert _is_nextjs_convention_entry("app/global-error.tsx") is True

    def test_template(self):
        assert _is_nextjs_convention_entry("app/template.tsx") is True

    def test_default_parallel_route(self):
        assert _is_nextjs_convention_entry("app/@modal/default.tsx") is True

    def test_opengraph_image(self):
        assert _is_nextjs_convention_entry("app/opengraph-image.tsx") is True

    def test_sitemap(self):
        assert _is_nextjs_convention_entry("app/sitemap.ts") is True

    def test_robots(self):
        assert _is_nextjs_convention_entry("app/robots.ts") is True

    def test_middleware_at_root(self):
        assert _is_nextjs_convention_entry("middleware.ts") is True

    def test_middleware_in_src(self):
        assert _is_nextjs_convention_entry("src/middleware.ts") is True

    def test_instrumentation_at_root(self):
        assert _is_nextjs_convention_entry("instrumentation.ts") is True

    def test_instrumentation_client(self):
        assert _is_nextjs_convention_entry("src/instrumentation-client.js") is True

    def test_page_in_src_app(self):
        assert _is_nextjs_convention_entry("src/app/page.tsx") is True

    def test_regular_file_in_app_not_matched(self):
        """A non-convention file inside app/ is NOT treated as entry."""
        assert _is_nextjs_convention_entry("app/utils/helpers.ts") is False

    def test_page_outside_app_not_matched(self):
        """page.tsx outside an app/ directory is NOT treated as entry."""
        assert _is_nextjs_convention_entry("src/components/page.tsx") is False

    def test_middleware_too_deep_not_matched(self):
        """middleware.ts nested more than one level deep is not an entry."""
        assert _is_nextjs_convention_entry("src/lib/middleware.ts") is False

    def test_non_js_extension_not_matched(self):
        assert _is_nextjs_convention_entry("app/page.py") is False

    def test_css_extension_not_matched(self):
        assert _is_nextjs_convention_entry("app/page.css") is False


class TestNextjsIntegration:
    """Integration tests for Next.js orphan detection in detect_orphaned_files."""

    def test_nextjs_app_router_files_not_orphaned(self, tmp_path):
        """Next.js convention files are excluded when next.config.js exists."""
        (tmp_path / "next.config.js").write_text("module.exports = {}")
        app_dir = tmp_path / "app"
        page = _write_file(app_dir / "page.tsx", lines=30)
        layout = _write_file(app_dir / "layout.tsx", lines=50)
        route = _write_file(app_dir / "api" / "route.ts", lines=20)
        orphan = _write_file(tmp_path / "src" / "orphan.ts", lines=25)

        graph = {
            str(page): _graph_entry(importer_count=0),
            str(layout): _graph_entry(importer_count=0),
            str(route): _graph_entry(importer_count=0),
            str(orphan): _graph_entry(importer_count=0),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(tmp_path, graph, [".ts", ".tsx"])

        assert total == 4
        assert len(entries) == 1
        assert entries[0]["file"] == str(orphan)

    def test_no_nextjs_config_no_exclusion(self, tmp_path):
        """Without next.config, convention files ARE reported as orphaned."""
        app_dir = tmp_path / "app"
        page = _write_file(app_dir / "page.tsx", lines=30)

        graph = {
            str(page): _graph_entry(importer_count=0),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(tmp_path, graph, [".tsx"])

        assert len(entries) == 1

    def test_detect_frameworks_false_disables(self, tmp_path):
        """Setting detect_frameworks=False skips Next.js detection."""
        (tmp_path / "next.config.js").write_text("module.exports = {}")
        page = _write_file(tmp_path / "app" / "page.tsx", lines=30)

        graph = {
            str(page): _graph_entry(importer_count=0),
        }

        with patch(
            "desloppify.engine.detectors.orphaned.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total = detect_orphaned_files(
                tmp_path,
                graph,
                [".tsx"],
                options=OrphanedDetectionOptions(detect_frameworks=False),
            )

        assert len(entries) == 1
