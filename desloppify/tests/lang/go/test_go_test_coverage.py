"""Tests for Go-specific coverage import mapping helpers."""

from __future__ import annotations

from desloppify.languages.go import test_coverage as go_cov


def test_resolve_import_spec_matches_relative_package_file():
    production = {"pkg/internal/util.go", "pkg/internal/mapper.go"}
    resolved = go_cov.resolve_import_spec("pkg/internal/util", "pkg/app/app_test.go", production)
    assert resolved == "pkg/internal/util.go"


def test_resolve_import_spec_matches_module_prefixed_path_by_suffix():
    production = {"pkg/service/handler.go"}
    resolved = go_cov.resolve_import_spec(
        "github.com/acme/project/pkg/service/handler",
        "pkg/service/handler_test.go",
        production,
    )
    assert resolved == "pkg/service/handler.go"


def test_resolve_import_spec_skips_special_imports():
    production = {"pkg/service/handler.go"}
    assert go_cov.resolve_import_spec("unsafe", "pkg/service/handler_test.go", production) is None


def test_map_test_to_sources_covers_whole_package():
    # Go compiles a directory as one package and `go test` reports coverage
    # package-wide, so one test file covers every sibling production file.
    production = {
        "internal/ingest/plan.go",
        "internal/ingest/verify.go",
        "internal/ingest/run.go",
        "internal/other/other.go",
    }
    covered = go_cov.map_test_to_sources("internal/ingest/ingest_test.go", production)
    assert covered == {
        "internal/ingest/plan.go",
        "internal/ingest/verify.go",
        "internal/ingest/run.go",
    }


def test_map_test_to_sources_ignores_non_test_files():
    production = {"internal/ingest/plan.go"}
    assert go_cov.map_test_to_sources("internal/ingest/notes.md", production) == set()
