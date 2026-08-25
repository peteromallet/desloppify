"""Tests for Rust language plugin configuration wiring."""

from __future__ import annotations

from desloppify.base.discovery.source import clear_source_file_cache_for_tests
from desloppify.base.runtime_state import RuntimeContext, runtime_scope
from desloppify.engine.hook_registry import get_lang_hook
from desloppify.engine.policy.zones import FileZoneMap, Zone
from desloppify.languages import get_lang


def test_config_detect_commands_populated():
    cfg = get_lang("rust")
    for name in (
        "deps",
        "cycles",
        "orphaned",
        "dupes",
        "large",
        "complexity",
        "smells",
        "clippy_warning",
        "cargo_error",
        "rustdoc_warning",
        "rust_import_hygiene",
        "rust_feature_hygiene",
        "rust_doctest",
        "rust_api_convention",
        "rust_error_boundary",
        "rust_future_proofing",
        "rust_thread_safety",
        "rust_async_locking",
        "rust_drop_safety",
        "rust_unsafe_api",
    ):
        assert name in cfg.detect_commands


def test_config_has_core_phases():
    cfg = get_lang("rust")
    labels = [phase.label for phase in cfg.phases]
    assert "Structural analysis" in labels
    assert "Coupling + cycles + orphaned" in labels
    assert "Rust API + cargo policy" in labels
    assert "cargo clippy" in labels
    assert "cargo check" in labels
    assert "cargo rustdoc" in labels
    assert "Test coverage" in labels
    assert "Code smells" in labels
    assert "Security" in labels


def test_config_excludes_generic_unused_imports_phase():
    cfg = get_lang("rust")
    labels = [phase.label for phase in cfg.phases]
    assert "Unused imports" not in labels


def test_config_metadata():
    cfg = get_lang("rust")
    assert cfg.integration_depth == "full"
    assert cfg.default_src == "src"
    assert cfg.detect_markers == ["Cargo.toml"]
    assert cfg.entry_patterns == [
        "src/lib.rs",
        "src/main.rs",
        "src/bin/",
        "tests/",
        "examples/",
        "benches/",
        "fuzz/",
        "build.rs",
    ]


def test_test_coverage_hooks_registered():
    assert get_lang_hook("rust", "test_coverage") is not None


def test_rust_zone_rules_classify_targets():
    cfg = get_lang("rust")
    zone_map = FileZoneMap(
        [
            "src/lib.rs",
            "src/bin/cli.rs",
            "src/cli_tests.rs",
            "src/policy/tests.rs",
            "src/schema/postgres_tests/bootstrap.rs",
            "src/test_cli.rs",
            "src/bin/cli_tests.rs",
            "tests/api.rs",
            "examples/demo.rs",
            "benches/bench.rs",
            "fuzz/fuzz_targets/render.rs",
            "build.rs",
            "Cargo.toml",
        ],
        cfg.zone_rules,
        rel_fn=lambda path: path,
    )
    assert zone_map.get("src/lib.rs") == Zone.PRODUCTION
    assert zone_map.get("src/bin/cli.rs") == Zone.PRODUCTION
    assert zone_map.get("src/cli_tests.rs") == Zone.TEST
    assert zone_map.get("src/policy/tests.rs") == Zone.TEST
    assert zone_map.get("src/schema/postgres_tests/bootstrap.rs") == Zone.TEST
    assert zone_map.get("src/test_cli.rs") == Zone.TEST
    assert zone_map.get("src/bin/cli_tests.rs") == Zone.PRODUCTION
    assert zone_map.get("tests/api.rs") == Zone.TEST
    assert zone_map.get("examples/demo.rs") == Zone.SCRIPT
    assert zone_map.get("benches/bench.rs") == Zone.SCRIPT
    assert zone_map.get("fuzz/fuzz_targets/render.rs") == Zone.SCRIPT
    assert zone_map.get("build.rs") == Zone.SCRIPT
    assert zone_map.get("Cargo.toml") == Zone.CONFIG


def test_file_finder_skips_target_artifacts(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("pub fn work() {}\n")
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "generated.rs").write_text("pub fn generated() {}\n")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "vendored.rs").write_text("pub fn vendored() {}\n")

    ctx = RuntimeContext(project_root=tmp_path)
    with runtime_scope(ctx):
        clear_source_file_cache_for_tests()
        files = get_lang("rust").file_finder(tmp_path)

    assert files == ["src/lib.rs"]
