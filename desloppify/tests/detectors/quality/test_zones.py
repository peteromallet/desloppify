"""Tests for desloppify.zones — zone classification, policies, and filtering."""

import pytest

from desloppify.engine.policy.zones import (
    COMMON_ZONE_RULES,
    EXCLUDED_ZONE_VALUES,
    EXCLUDED_ZONES,
    ZONE_POLICIES,
    FileZoneMap,
    Zone,
    ZonePolicy,
    ZoneRule,
    _match_pattern,
    adjust_potential,
    classify_file,
    filter_entries,
    should_skip_finding,
)

# ── _match_pattern() ─────────────────────────────────────────


class TestMatchPattern:
    """Tests for the _match_pattern helper."""

    def test_directory_pattern_matches(self):
        """'/tests/' matches a file inside a tests directory."""
        assert _match_pattern("src/tests/foo.py", "/tests/") is True

    def test_directory_pattern_at_root(self):
        """'/tests/' matches a file at the root-level tests dir."""
        assert _match_pattern("tests/foo.py", "/tests/") is True

    def test_directory_pattern_no_false_positive(self):
        """'/tests/' does NOT match 'attestation.py' (substring only)."""
        assert _match_pattern("attestation.py", "/tests/") is False

    def test_directory_pattern_nested(self):
        """'/vendor/' matches a deeply nested vendor directory."""
        assert _match_pattern("lib/vendor/pkg/file.js", "/vendor/") is True

    def test_directory_pattern_must_be_component(self):
        """'/test/' does not match 'testimony/foo.py' — needs directory boundary."""
        assert _match_pattern("testimony/foo.py", "/test/") is False

    def test_suffix_extension_pattern(self):
        """'.test.' matches 'foo.test.ts' via contains on basename."""
        assert _match_pattern("src/foo.test.ts", ".test.") is True

    def test_suffix_extension_pattern_tsx(self):
        """'.test.' matches 'Component.test.tsx'."""
        assert _match_pattern("components/Component.test.tsx", ".test.") is True

    def test_suffix_extension_pattern_no_match(self):
        """'.test.' does NOT match 'test_utils.py' (no '.test.' substring)."""
        assert _match_pattern("test_utils.py", ".test.") is False

    def test_dot_extension_pattern(self):
        """'.d.ts' matches 'types.d.ts' via contains on basename."""
        assert _match_pattern("src/types.d.ts", ".d.ts") is True

    def test_dot_extension_no_match(self):
        """'.d.ts' does NOT match 'data.ts'."""
        assert _match_pattern("src/data.ts", ".d.ts") is False

    def test_prefix_pattern_matches(self):
        """'test_' matches 'test_foo.py' — basename starts with prefix."""
        assert _match_pattern("test_foo.py", "test_") is True

    def test_prefix_pattern_with_directory(self):
        """'test_' matches 'src/test_bar.py'."""
        assert _match_pattern("src/test_bar.py", "test_") is True

    def test_prefix_pattern_no_match(self):
        """'test_' does NOT match 'contest_results.py' — no prefix match."""
        assert _match_pattern("contest_results.py", "test_") is False

    def test_suffix_underscore_pattern(self):
        """'_test.py' matches 'foo_test.py' — basename ends with suffix."""
        assert _match_pattern("foo_test.py", "_test.py") is True

    def test_suffix_underscore_pattern_with_dir(self):
        """'_test.py' matches 'src/bar_test.py'."""
        assert _match_pattern("src/bar_test.py", "_test.py") is True

    def test_suffix_underscore_no_match(self):
        """'_test.py' does NOT match 'test_foo.py'."""
        assert _match_pattern("test_foo.py", "_test.py") is False

    def test_suffix_pb2(self):
        """'_pb2.py' matches 'message_pb2.py'."""
        assert _match_pattern("protos/message_pb2.py", "_pb2.py") is True

    def test_exact_basename_match(self):
        """'config.py' matches 'src/config.py' — exact basename."""
        assert _match_pattern("src/config.py", "config.py") is True

    def test_exact_basename_no_match(self):
        """'config.py' does NOT match 'src/myconfig.py'."""
        assert _match_pattern("src/myconfig.py", "config.py") is False

    def test_exact_basename_conftest(self):
        """'conftest.py' matches 'tests/conftest.py'."""
        assert _match_pattern("tests/conftest.py", "conftest.py") is True

    def test_exact_basename_setup(self):
        """'setup.py' matches 'setup.py' at root."""
        assert _match_pattern("setup.py", "setup.py") is True

    def test_fallback_substring_match(self):
        """Fallback substring matches on full path (e.g. 'tsconfig')."""
        assert _match_pattern("project/tsconfig.json", "tsconfig") is True

    def test_fallback_substring_no_match(self):
        """Fallback substring does NOT match unrelated paths."""
        assert _match_pattern("src/app.ts", "tsconfig") is False

    def test_fallback_vite_config(self):
        """'vite.config' matches 'vite.config.ts' via fallback substring."""
        assert _match_pattern("vite.config.ts", "vite.config") is True


# ── classify_file() ──────────────────────────────────────────


class TestClassifyFile:
    """Tests for the classify_file function."""

    def test_vendor_directory(self):
        """File in vendor/ is classified as VENDOR."""
        assert classify_file("lib/vendor/pkg.py", COMMON_ZONE_RULES) == Zone.VENDOR

    def test_third_party_directory(self):
        """File in third_party/ is classified as VENDOR."""
        assert classify_file("third_party/lib.py", COMMON_ZONE_RULES) == Zone.VENDOR

    def test_vendored_directory(self):
        """File in vendored/ is classified as VENDOR."""
        assert classify_file("vendored/dep.py", COMMON_ZONE_RULES) == Zone.VENDOR

    def test_generated_directory(self):
        """File in generated/ is classified as GENERATED."""
        assert (
            classify_file("src/generated/types.py", COMMON_ZONE_RULES) == Zone.GENERATED
        )

    def test_dunder_generated_directory(self):
        """File in __generated__/ is classified as GENERATED."""
        assert (
            classify_file("__generated__/schema.py", COMMON_ZONE_RULES)
            == Zone.GENERATED
        )

    def test_tests_directory(self):
        """File in tests/ is classified as TEST."""
        assert classify_file("tests/test_foo.py", COMMON_ZONE_RULES) == Zone.TEST

    def test_test_directory(self):
        """File in test/ is classified as TEST."""
        assert classify_file("test/test_bar.py", COMMON_ZONE_RULES) == Zone.TEST

    def test_fixtures_directory(self):
        """File in fixtures/ is classified as TEST."""
        assert classify_file("fixtures/data.json", COMMON_ZONE_RULES) == Zone.TEST

    def test_scripts_directory(self):
        """File in scripts/ is classified as SCRIPT."""
        assert classify_file("scripts/deploy.sh", COMMON_ZONE_RULES) == Zone.SCRIPT

    def test_bin_directory(self):
        """File in bin/ is classified as SCRIPT."""
        assert classify_file("bin/run.py", COMMON_ZONE_RULES) == Zone.SCRIPT

    def test_production_default(self):
        """File not matching any rule defaults to PRODUCTION."""
        assert classify_file("src/app.py", COMMON_ZONE_RULES) == Zone.PRODUCTION

    def test_production_unknown_path(self):
        """Completely unrecognized path defaults to PRODUCTION."""
        assert (
            classify_file("lib/utils/helpers.py", COMMON_ZONE_RULES) == Zone.PRODUCTION
        )

    def test_first_matching_rule_wins(self):
        """VENDOR comes before TEST in COMMON_ZONE_RULES, so vendor wins."""
        # A file in vendor/tests/ should be VENDOR (first match)
        assert classify_file("vendor/tests/test_x.py", COMMON_ZONE_RULES) == Zone.VENDOR

    def test_override_takes_priority(self):
        """Override value takes priority over rule-based classification."""
        overrides = {"src/app.py": "test"}
        assert classify_file("src/app.py", COMMON_ZONE_RULES, overrides) == Zone.TEST

    def test_override_on_vendor_file(self):
        """Override can reclassify a vendor file as production."""
        overrides = {"vendor/special.py": "production"}
        assert (
            classify_file("vendor/special.py", COMMON_ZONE_RULES, overrides)
            == Zone.PRODUCTION
        )

    def test_override_invalid_zone_falls_through(self):
        """Invalid zone value in override falls through to rule matching."""
        overrides = {"scripts/run.py": "invalid_zone"}
        assert (
            classify_file("scripts/run.py", COMMON_ZONE_RULES, overrides) == Zone.SCRIPT
        )

    def test_override_missing_key_falls_through(self):
        """Override dict present but file not in it falls through to rules."""
        overrides = {"other.py": "test"}
        assert (
            classify_file("src/app.py", COMMON_ZONE_RULES, overrides) == Zone.PRODUCTION
        )

    def test_override_none(self):
        """overrides=None is handled gracefully."""
        assert classify_file("src/app.py", COMMON_ZONE_RULES, None) == Zone.PRODUCTION

    def test_empty_rules(self):
        """Empty rules list defaults everything to PRODUCTION."""
        assert classify_file("tests/test_foo.py", []) == Zone.PRODUCTION

    def test_custom_rules(self):
        """Custom rules correctly classify files."""
        rules = [ZoneRule(Zone.CONFIG, ["config.py", ".cfg"])]
        assert classify_file("src/config.py", rules) == Zone.CONFIG
        assert classify_file("setup.cfg", rules) == Zone.CONFIG
        assert classify_file("src/main.py", rules) == Zone.PRODUCTION


# ── FileZoneMap ──────────────────────────────────────────────


class TestFileZoneMap:
    """Tests for the FileZoneMap class."""

    @pytest.fixture
    def sample_files(self):
        """A set of files spanning multiple zones."""
        return [
            "src/app.py",
            "src/utils.py",
            "tests/test_app.py",
            "tests/test_utils.py",
            "scripts/deploy.sh",
            "vendor/lib.py",
            "generated/types.py",
        ]

    @pytest.fixture
    def zone_map(self, sample_files):
        """FileZoneMap built from sample files and common rules."""
        return FileZoneMap(sample_files, COMMON_ZONE_RULES)

    def test_get_production_file(self, zone_map):
        """Production file returns Zone.PRODUCTION."""
        assert zone_map.get("src/app.py") == Zone.PRODUCTION

    def test_get_test_file(self, zone_map):
        """Test file returns Zone.TEST."""
        assert zone_map.get("tests/test_app.py") == Zone.TEST

    def test_get_script_file(self, zone_map):
        """Script file returns Zone.SCRIPT."""
        assert zone_map.get("scripts/deploy.sh") == Zone.SCRIPT

    def test_get_vendor_file(self, zone_map):
        """Vendor file returns Zone.VENDOR."""
        assert zone_map.get("vendor/lib.py") == Zone.VENDOR

    def test_get_generated_file(self, zone_map):
        """Generated file returns Zone.GENERATED."""
        assert zone_map.get("generated/types.py") == Zone.GENERATED

    def test_get_unknown_file_defaults_production(self, zone_map):
        """File not in the map returns PRODUCTION."""
        assert zone_map.get("unknown/file.py") == Zone.PRODUCTION

    def test_exclude_zones(self, zone_map, sample_files):
        """exclude() removes files in specified zones."""
        result = zone_map.exclude(sample_files, Zone.TEST, Zone.VENDOR)
        assert "tests/test_app.py" not in result
        assert "tests/test_utils.py" not in result
        assert "vendor/lib.py" not in result
        assert "src/app.py" in result
        assert "scripts/deploy.sh" in result

    def test_exclude_no_zones(self, zone_map, sample_files):
        """exclude() with no zones returns all files."""
        result = zone_map.exclude(sample_files)
        assert len(result) == len(sample_files)

    def test_include_only_zones(self, zone_map, sample_files):
        """include_only() returns files in specified zones."""
        result = zone_map.include_only(sample_files, Zone.TEST)
        assert len(result) == 2
        assert "tests/test_app.py" in result
        assert "tests/test_utils.py" in result

    def test_include_only_multiple_zones(self, zone_map, sample_files):
        """include_only() works with multiple zones."""
        result = zone_map.include_only(sample_files, Zone.PRODUCTION, Zone.SCRIPT)
        assert "src/app.py" in result
        assert "src/utils.py" in result
        assert "scripts/deploy.sh" in result
        assert len(result) == 3

    def test_include_only_empty_result(self, zone_map, sample_files):
        """include_only() with zone having no files returns empty."""
        result = zone_map.include_only(sample_files, Zone.CONFIG)
        assert result == []

    def test_counts(self, zone_map):
        """counts() returns correct per-zone tallies."""
        c = zone_map.counts()
        assert c["production"] == 2
        assert c["test"] == 2
        assert c["script"] == 1
        assert c["vendor"] == 1
        assert c["generated"] == 1

    def test_production_count(self, zone_map):
        """production_count() returns total minus non-production (SCRIPT is not excluded)."""
        # 7 files - 4 non-production (2 test + 1 vendor + 1 generated) = 3
        # (SCRIPT is NOT in EXCLUDED_ZONES so it counts toward production_count)
        assert zone_map.production_count() == 3

    def test_non_production_count(self, zone_map):
        """non_production_count() returns count of excluded-zone files."""
        # test(2) + vendor(1) + generated(1) = 4 (script is NOT in EXCLUDED_ZONES)
        assert zone_map.non_production_count() == 4

    def test_all_files(self, zone_map, sample_files):
        """all_files() returns the full file list."""
        result = zone_map.all_files()
        assert set(result) == set(sample_files)

    def test_items(self, zone_map, sample_files):
        """items() returns (path, zone) tuples for all files."""
        result = zone_map.items()
        assert len(result) == len(sample_files)
        result_dict = dict(result)
        assert result_dict["src/app.py"] == Zone.PRODUCTION
        assert result_dict["tests/test_app.py"] == Zone.TEST

    def test_rel_fn(self):
        """rel_fn is used to convert paths before classification."""
        files = ["/project/tests/test_foo.py", "/project/src/main.py"]

        def strip_prefix(p):
            return p.replace("/project/", "")

        zm = FileZoneMap(files, COMMON_ZONE_RULES, rel_fn=strip_prefix)
        assert zm.get("/project/tests/test_foo.py") == Zone.TEST
        assert zm.get("/project/src/main.py") == Zone.PRODUCTION

    def test_overrides(self):
        """Overrides are passed through to classify_file."""
        files = ["src/special.py"]
        overrides = {"src/special.py": "test"}
        zm = FileZoneMap(files, COMMON_ZONE_RULES, overrides=overrides)
        assert zm.get("src/special.py") == Zone.TEST

    def test_empty_file_list(self):
        """FileZoneMap with no files works correctly."""
        zm = FileZoneMap([], COMMON_ZONE_RULES)
        assert zm.all_files() == []
        assert zm.counts() == {}
        assert zm.production_count() == 0
        assert zm.non_production_count() == 0

    def test_exclude_with_unknown_files(self, zone_map):
        """exclude() handles files not in the map (defaulting to PRODUCTION)."""
        files = ["src/app.py", "unknown.py"]
        result = zone_map.exclude(files, Zone.PRODUCTION)
        # Both are PRODUCTION (one explicitly, one by default), so both excluded
        assert result == []

    def test_include_only_with_unknown_files(self, zone_map):
        """include_only() handles files not in the map (defaulting to PRODUCTION)."""
        files = ["src/app.py", "unknown.py"]
        result = zone_map.include_only(files, Zone.PRODUCTION)
        assert len(result) == 2


# ── Zone / EXCLUDED_ZONES / EXCLUDED_ZONE_VALUES ────────────


class TestZoneEnumAndConstants:
    """Tests for Zone enum and related constants."""

    def test_zone_values(self):
        """All expected zone values exist."""
        assert Zone.PRODUCTION.value == "production"
        assert Zone.TEST.value == "test"
        assert Zone.CONFIG.value == "config"
        assert Zone.GENERATED.value == "generated"
        assert Zone.SCRIPT.value == "script"
        assert Zone.VENDOR.value == "vendor"

    def test_zone_is_str(self):
        """Zone is a str enum."""
        assert isinstance(Zone.PRODUCTION, str)

    def test_excluded_zones(self):
        """EXCLUDED_ZONES contains the correct zones."""
        assert EXCLUDED_ZONES == {Zone.TEST, Zone.CONFIG, Zone.GENERATED, Zone.VENDOR}
        # SCRIPT and PRODUCTION are NOT excluded
        assert Zone.SCRIPT not in EXCLUDED_ZONES
        assert Zone.PRODUCTION not in EXCLUDED_ZONES

    def test_excluded_zone_values(self):
        """EXCLUDED_ZONE_VALUES contains string values of excluded zones."""
        assert EXCLUDED_ZONE_VALUES == {"test", "config", "generated", "vendor"}


# ── ZONE_POLICIES ────────────────────────────────────────────


class TestZonePolicies:
    """Tests for zone policy definitions."""

    def test_production_policy_is_permissive(self):
        """PRODUCTION policy has no skips or downgrades."""
        policy = ZONE_POLICIES[Zone.PRODUCTION]
        assert policy.skip_detectors == set()
        assert policy.downgrade_detectors == set()
        assert policy.exclude_from_score is False

    def test_test_zone_skips(self):
        """TEST zone skips expected detectors."""
        policy = ZONE_POLICIES[Zone.TEST]
        expected_skips = {
            "boilerplate_duplication",
            "dupes",
            "single_use",
            "orphaned",
            "coupling",
            "facade",
            "dict_keys",
            "test_coverage",
            "security",
            "private_imports",
        }
        assert policy.skip_detectors == expected_skips

    def test_test_zone_downgrades(self):
        """TEST zone downgrades smells and structural."""
        policy = ZONE_POLICIES[Zone.TEST]
        assert policy.downgrade_detectors == {"smells", "structural"}

    def test_test_zone_excluded_from_score(self):
        """TEST zone is excluded from scoring."""
        assert ZONE_POLICIES[Zone.TEST].exclude_from_score is True

    def test_config_zone_skips(self):
        """CONFIG zone skips a broad set of detectors."""
        policy = ZONE_POLICIES[Zone.CONFIG]
        expected_skips = {
            "boilerplate_duplication",
            "smells",
            "structural",
            "dupes",
            "naming",
            "single_use",
            "orphaned",
            "coupling",
            "facade",
            "dict_keys",
            "test_coverage",
            "security",
        }
        assert policy.skip_detectors == expected_skips

    def test_config_zone_excluded_from_score(self):
        """CONFIG zone is excluded from scoring."""
        assert ZONE_POLICIES[Zone.CONFIG].exclude_from_score is True

    def test_generated_zone_skips_most(self):
        """GENERATED zone skips nearly all detectors."""
        policy = ZONE_POLICIES[Zone.GENERATED]
        assert "test_coverage" in policy.skip_detectors
        assert "unused" in policy.skip_detectors
        assert "smells" in policy.skip_detectors
        assert "react" in policy.skip_detectors
        assert "naming" in policy.skip_detectors
        assert "cycles" in policy.skip_detectors

    def test_generated_zone_excluded_from_score(self):
        """GENERATED zone is excluded from scoring."""
        assert ZONE_POLICIES[Zone.GENERATED].exclude_from_score is True

    def test_vendor_zone_matches_generated(self):
        """VENDOR zone has the same skip set as GENERATED."""
        vendor = ZONE_POLICIES[Zone.VENDOR]
        generated = ZONE_POLICIES[Zone.GENERATED]
        assert vendor.skip_detectors == generated.skip_detectors
        assert vendor.exclude_from_score is True

    def test_script_zone_skips(self):
        """SCRIPT zone skips coupling, single_use, orphaned, facade."""
        policy = ZONE_POLICIES[Zone.SCRIPT]
        assert policy.skip_detectors == {"coupling", "single_use", "orphaned", "facade"}

    def test_script_zone_downgrades_structural(self):
        """SCRIPT zone downgrades structural."""
        assert ZONE_POLICIES[Zone.SCRIPT].downgrade_detectors == {"structural"}

    def test_script_zone_not_excluded_from_score(self):
        """SCRIPT zone is NOT excluded from scoring."""
        assert ZONE_POLICIES[Zone.SCRIPT].exclude_from_score is False

    def test_all_non_production_zones_skip_test_coverage(self):
        """test_coverage is in skip_detectors for TEST, CONFIG, GENERATED, VENDOR."""
        for zone in [Zone.TEST, Zone.CONFIG, Zone.GENERATED, Zone.VENDOR]:
            policy = ZONE_POLICIES[zone]
            assert "test_coverage" in policy.skip_detectors, (
                f"{zone.value} zone should skip test_coverage"
            )

    def test_production_does_not_skip_test_coverage(self):
        """PRODUCTION zone does NOT skip test_coverage."""
        assert "test_coverage" not in ZONE_POLICIES[Zone.PRODUCTION].skip_detectors

    def test_script_does_not_skip_test_coverage(self):
        """SCRIPT zone does NOT skip test_coverage."""
        assert "test_coverage" not in ZONE_POLICIES[Zone.SCRIPT].skip_detectors

    def test_every_zone_has_policy(self):
        """Every Zone enum value has a corresponding policy."""
        for zone in Zone:
            assert zone in ZONE_POLICIES, f"Missing policy for {zone.value}"


# ── adjust_potential() ───────────────────────────────────────


class TestAdjustPotential:
    """Tests for the adjust_potential helper."""

    def test_with_zone_map(self):
        """Subtracts non-production count from total."""
        files = [
            "src/app.py",
            "tests/test_app.py",
            "vendor/lib.py",
        ]
        zm = FileZoneMap(files, COMMON_ZONE_RULES)
        # non_production = test(1) + vendor(1) = 2
        result = adjust_potential(zm, 10)
        assert result == 8

    def test_with_zone_map_all_production(self):
        """No adjustment when all files are production."""
        files = ["src/app.py", "src/utils.py"]
        zm = FileZoneMap(files, COMMON_ZONE_RULES)
        assert adjust_potential(zm, 5) == 5

    def test_with_zone_map_clamps_to_zero(self):
        """Result is clamped to 0 if non-production exceeds total."""
        files = ["tests/a.py", "tests/b.py", "vendor/c.py"]
        zm = FileZoneMap(files, COMMON_ZONE_RULES)
        # All 3 are non-production, total is 1
        assert adjust_potential(zm, 1) == 0

    def test_none_zone_map(self):
        """Returns total unchanged when zone_map is None."""
        assert adjust_potential(None, 42) == 42

    def test_zero_total(self):
        """Zero total stays zero."""
        files = ["src/app.py"]
        zm = FileZoneMap(files, COMMON_ZONE_RULES)
        assert adjust_potential(zm, 0) == 0


# ── should_skip_finding() ────────────────────────────────────


class TestShouldSkipFinding:
    """Tests for the should_skip_finding helper."""

    @pytest.fixture
    def zone_map(self):
        files = [
            "src/app.py",
            "tests/test_app.py",
            "scripts/deploy.sh",
            "vendor/lib.py",
        ]
        return FileZoneMap(files, COMMON_ZONE_RULES)

    def test_skip_in_test_zone(self, zone_map):
        """Detectors in TEST skip_detectors are skipped for test files."""
        assert should_skip_finding(zone_map, "tests/test_app.py", "dupes") is True
        assert should_skip_finding(zone_map, "tests/test_app.py", "coupling") is True
        assert (
            should_skip_finding(zone_map, "tests/test_app.py", "test_coverage") is True
        )
        assert should_skip_finding(zone_map, "tests/test_app.py", "security") is True

    def test_allow_in_test_zone(self, zone_map):
        """Detectors NOT in TEST skip_detectors are allowed for test files."""
        assert should_skip_finding(zone_map, "tests/test_app.py", "unused") is False
        assert should_skip_finding(zone_map, "tests/test_app.py", "logs") is False

    def test_production_never_skips(self, zone_map):
        """PRODUCTION zone never skips any detector."""
        assert should_skip_finding(zone_map, "src/app.py", "dupes") is False
        assert should_skip_finding(zone_map, "src/app.py", "smells") is False
        assert should_skip_finding(zone_map, "src/app.py", "coupling") is False

    def test_vendor_skips_most(self, zone_map):
        """VENDOR zone skips most detectors."""
        assert should_skip_finding(zone_map, "vendor/lib.py", "unused") is True
        assert should_skip_finding(zone_map, "vendor/lib.py", "smells") is True
        assert should_skip_finding(zone_map, "vendor/lib.py", "naming") is True
        assert should_skip_finding(zone_map, "vendor/lib.py", "test_coverage") is True

    def test_script_skips_subset(self, zone_map):
        """SCRIPT zone skips only its specific detectors."""
        assert should_skip_finding(zone_map, "scripts/deploy.sh", "coupling") is True
        assert should_skip_finding(zone_map, "scripts/deploy.sh", "facade") is True
        # But not smells
        assert should_skip_finding(zone_map, "scripts/deploy.sh", "smells") is False

    def test_none_zone_map_never_skips(self):
        """Returns False when zone_map is None (backward compat)."""
        assert should_skip_finding(None, "tests/test_app.py", "dupes") is False

    def test_unknown_file_defaults_production(self, zone_map):
        """File not in the map is treated as PRODUCTION (no skips)."""
        assert should_skip_finding(zone_map, "unknown.py", "dupes") is False


# ── filter_entries() ─────────────────────────────────────────


class TestFilterEntries:
    """Tests for the filter_entries helper."""

    @pytest.fixture
    def zone_map(self):
        files = [
            "src/app.py",
            "tests/test_app.py",
            "vendor/lib.py",
        ]
        return FileZoneMap(files, COMMON_ZONE_RULES)

    def test_removes_skipped_entries(self, zone_map):
        """Entries from skipped zones are removed."""
        entries = [
            {"file": "src/app.py", "msg": "dupe 1"},
            {"file": "tests/test_app.py", "msg": "dupe 2"},
        ]
        result = filter_entries(zone_map, entries, "dupes")
        assert len(result) == 1
        assert result[0]["file"] == "src/app.py"

    def test_keeps_allowed_entries(self, zone_map):
        """Entries from allowed zones are kept."""
        entries = [
            {"file": "src/app.py", "msg": "unused 1"},
            {"file": "tests/test_app.py", "msg": "unused 2"},
        ]
        # "unused" is not skipped in TEST zone
        result = filter_entries(zone_map, entries, "unused")
        assert len(result) == 2

    def test_vendor_entries_filtered(self, zone_map):
        """Entries from vendor zone are filtered for smells detector."""
        entries = [
            {"file": "src/app.py", "msg": "smell 1"},
            {"file": "vendor/lib.py", "msg": "smell 2"},
        ]
        result = filter_entries(zone_map, entries, "smells")
        assert len(result) == 1
        assert result[0]["file"] == "src/app.py"

    def test_custom_file_key(self, zone_map):
        """Custom file_key extracts the path from a different key."""
        entries = [
            {"path": "src/app.py", "msg": "ok"},
            {"path": "tests/test_app.py", "msg": "skip"},
        ]
        result = filter_entries(zone_map, entries, "dupes", file_key="path")
        assert len(result) == 1
        assert result[0]["path"] == "src/app.py"

    def test_list_file_key(self, zone_map):
        """When file_key points to a list, checks the first element."""
        entries = [
            {"files": ["src/app.py", "src/utils.py"], "msg": "cycle 1"},
            {"files": ["tests/test_app.py", "tests/test_utils.py"], "msg": "cycle 2"},
        ]
        result = filter_entries(zone_map, entries, "coupling", file_key="files")
        assert len(result) == 1
        assert result[0]["msg"] == "cycle 1"

    def test_none_zone_map_noop(self):
        """Returns entries unchanged when zone_map is None."""
        entries = [
            {"file": "tests/test_app.py", "msg": "dupe"},
        ]
        result = filter_entries(None, entries, "dupes")
        assert result == entries

    def test_empty_entries(self, zone_map):
        """Empty entries list returns empty list."""
        assert filter_entries(zone_map, [], "dupes") == []

    def test_all_entries_filtered(self, zone_map):
        """All entries removed when all are in skipped zones."""
        entries = [
            {"file": "tests/test_app.py", "msg": "dupe 1"},
        ]
        result = filter_entries(zone_map, entries, "dupes")
        assert result == []


# ── ZoneRule dataclass ───────────────────────────────────────


class TestZoneRule:
    """Tests for the ZoneRule dataclass."""

    def test_construction(self):
        """ZoneRule stores zone and patterns."""
        rule = ZoneRule(Zone.TEST, ["/test/", ".spec."])
        assert rule.zone == Zone.TEST
        assert rule.patterns == ["/test/", ".spec."]


# ── ZonePolicy dataclass ────────────────────────────────────


class TestZonePolicy:
    """Tests for the ZonePolicy dataclass."""

    def test_default_construction(self):
        """Default ZonePolicy has empty sets and False exclude."""
        policy = ZonePolicy()
        assert policy.skip_detectors == set()
        assert policy.downgrade_detectors == set()
        assert policy.exclude_from_score is False

    def test_custom_construction(self):
        """ZonePolicy with custom values."""
        policy = ZonePolicy(
            skip_detectors={"unused", "smells"},
            downgrade_detectors={"structural"},
            exclude_from_score=True,
        )
        assert policy.skip_detectors == {"unused", "smells"}
        assert policy.downgrade_detectors == {"structural"}
        assert policy.exclude_from_score is True
