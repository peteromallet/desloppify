"""Tests for security detector internals: detector.py orchestration and filters.py."""

from __future__ import annotations

from desloppify.engine.detectors.security.detector import detect_security_issues
from desloppify.engine.detectors.security.filters import (
    _EXCLUDED_SECURITY_ZONES,
    _is_test_file,
    _should_scan_file,
    _should_skip_line,
)
from desloppify.engine.policy.zones import FileZoneMap, Zone, ZoneRule

# ── Helpers ───────────────────────────────────────────────────────────


def _make_zone_map(file_zone_pairs: list[tuple[str, Zone]]) -> FileZoneMap:
    """Build a FileZoneMap from explicit (filepath, zone) assignments."""
    files = [f for f, _ in file_zone_pairs]
    # Build rules that match exact filenames to zones
    rules: list[ZoneRule] = []
    for filepath, zone in file_zone_pairs:
        rules.append(ZoneRule(zone=zone, patterns=[filepath]))
    return FileZoneMap(files, rules)


# ── filters.py: _should_scan_file ────────────────────────────────────


def test_should_scan_file_no_zone_map():
    """When zone_map is None, all files should be scanned."""
    assert _should_scan_file("/any/file.py", None) is True


def test_should_scan_file_production_zone():
    """Production files should be scanned."""
    zm = _make_zone_map([("/app/main.py", Zone.PRODUCTION)])
    assert _should_scan_file("/app/main.py", zm) is True


def test_should_scan_file_test_zone_excluded():
    """Test files are excluded from security scanning."""
    zm = _make_zone_map([("/tests/test_foo.py", Zone.TEST)])
    assert _should_scan_file("/tests/test_foo.py", zm) is False


def test_should_scan_file_vendor_zone_excluded():
    """Vendor files are excluded from security scanning."""
    zm = _make_zone_map([("/vendor/lib.py", Zone.VENDOR)])
    assert _should_scan_file("/vendor/lib.py", zm) is False


def test_should_scan_file_generated_zone_excluded():
    """Generated files are excluded from security scanning."""
    zm = _make_zone_map([("/generated/schema.py", Zone.GENERATED)])
    assert _should_scan_file("/generated/schema.py", zm) is False


def test_should_scan_file_config_zone_excluded():
    """Config files are excluded from security scanning."""
    zm = _make_zone_map([("/config.py", Zone.CONFIG)])
    assert _should_scan_file("/config.py", zm) is False


def test_should_scan_file_script_zone_allowed():
    """Script zone is NOT in the excluded set, so scripts are scanned."""
    zm = _make_zone_map([("/scripts/deploy.py", Zone.SCRIPT)])
    assert _should_scan_file("/scripts/deploy.py", zm) is True


# ── filters.py: _is_test_file ────────────────────────────────────────


def test_is_test_file_no_zone_map():
    """When zone_map is None, result is False."""
    assert _is_test_file("/tests/test_foo.py", None) is False


def test_is_test_file_test_zone():
    """Files in test zone return True."""
    zm = _make_zone_map([("/tests/test_foo.py", Zone.TEST)])
    assert _is_test_file("/tests/test_foo.py", zm) is True


def test_is_test_file_production_zone():
    """Files in production zone return False."""
    zm = _make_zone_map([("/app/main.py", Zone.PRODUCTION)])
    assert _is_test_file("/app/main.py", zm) is False


# ── filters.py: _should_skip_line ────────────────────────────────────


def test_should_skip_line_normal_code():
    """Normal code lines should not be skipped."""
    assert _should_skip_line("password = os.environ['DB_PASS']") is False


def test_should_skip_line_comment_no_secret():
    """Comment lines without secret patterns should be skipped."""
    assert _should_skip_line("# this is a normal comment") is True


def test_should_skip_line_comment_with_secret_format():
    """Comment lines containing a secret format match should NOT be skipped."""
    # An AWS key in a comment is still flagged
    assert _should_skip_line("# AKIAIOSFODNN7EXAMPLE") is False


def test_should_skip_line_js_comment():
    """JS-style comments are recognized."""
    assert _should_skip_line("// just a note") is True


def test_should_skip_line_star_comment():
    """Block comment continuation lines are recognized."""
    assert _should_skip_line(" * @param foo the foo value") is True


# ── filters.py: _EXCLUDED_SECURITY_ZONES ─────────────────────────────


def test_excluded_security_zones_membership():
    """Verify the exact membership of excluded zones."""
    assert Zone.TEST in _EXCLUDED_SECURITY_ZONES
    assert Zone.CONFIG in _EXCLUDED_SECURITY_ZONES
    assert Zone.GENERATED in _EXCLUDED_SECURITY_ZONES
    assert Zone.VENDOR in _EXCLUDED_SECURITY_ZONES
    assert Zone.PRODUCTION not in _EXCLUDED_SECURITY_ZONES
    assert Zone.SCRIPT not in _EXCLUDED_SECURITY_ZONES


# ── detector.py: detect_security_issues ──────────────────────────────


def test_detect_security_issues_empty_files():
    """Empty file list yields no entries and zero scanned."""
    entries, scanned = detect_security_issues([], None, "python")
    assert entries == []
    assert scanned == 0


def test_detect_security_issues_unreadable_file(tmp_path):
    """Unreadable file is silently skipped."""
    bad = str(tmp_path / "nonexistent.py")
    entries, scanned = detect_security_issues([bad], None, "python")
    assert entries == []
    assert scanned == 0


def test_detect_security_issues_clean_file(tmp_path):
    """A file with no security issues produces no entries."""
    f = tmp_path / "clean.py"
    f.write_text("x = 42\nprint(x)\n")
    entries, scanned = detect_security_issues([str(f)], None, "python")
    assert entries == []
    assert scanned == 1


def test_detect_security_issues_resolves_relative_paths_with_scan_root(tmp_path):
    """Relative file paths are resolved from scan_root for consistent detector IO."""
    scan_root = tmp_path / "workspace"
    src = scan_root / "src"
    src.mkdir(parents=True, exist_ok=True)
    target = src / "creds.py"
    target.write_text('aws_key = "AKIAIOSFODNN7EXAMPLE"\n')

    entries, scanned = detect_security_issues(
        ["src/creds.py"],
        None,
        "python",
        scan_root=scan_root,
    )
    assert scanned == 1
    assert entries


def test_detect_security_issues_finds_aws_key(tmp_path):
    """A file with a hardcoded AWS key is detected."""
    f = tmp_path / "creds.py"
    f.write_text('aws_key = "AKIAIOSFODNN7EXAMPLE"\n')
    entries, scanned = detect_security_issues([str(f)], None, "python")
    assert scanned == 1
    assert len(entries) >= 1
    # At least one entry should reference the secret
    kinds = {e.get("detail", {}).get("kind") for e in entries}
    assert "hardcoded_secret_value" in kinds or "hardcoded_secret_name" in kinds


def test_detect_security_issues_skips_excluded_zone(tmp_path):
    """Files in excluded zones are not scanned."""
    f = tmp_path / "test_creds.py"
    f.write_text('aws_key = "AKIAIOSFODNN7EXAMPLE"\n')
    zm = _make_zone_map([(str(f), Zone.TEST)])
    entries, scanned = detect_security_issues([str(f)], zm, "python")
    assert scanned == 0
    assert entries == []


def test_detect_security_issues_weak_crypto(tmp_path):
    """TLS verification disabled is detected."""
    f = tmp_path / "http_client.py"
    f.write_text("requests.get(url, verify = False)\n")
    entries, scanned = detect_security_issues([str(f)], None, "python")
    assert scanned == 1
    assert len(entries) >= 1
    kinds = {e.get("detail", {}).get("kind") for e in entries}
    assert "weak_crypto_tls" in kinds


def test_detect_security_issues_sensitive_log(tmp_path):
    """Logging sensitive data is detected."""
    f = tmp_path / "app.py"
    f.write_text('logger.info("User password is", password)\n')
    entries, scanned = detect_security_issues([str(f)], None, "python")
    assert scanned == 1
    assert len(entries) >= 1
    kinds = {e.get("detail", {}).get("kind") for e in entries}
    assert "log_sensitive" in kinds


def test_detect_security_issues_insecure_random(tmp_path):
    """Insecure random in security context is detected."""
    f = tmp_path / "auth.py"
    f.write_text("token = random.random() # generate session token\n")
    entries, scanned = detect_security_issues([str(f)], None, "python")
    assert scanned == 1
    assert len(entries) >= 1
    kinds = {e.get("detail", {}).get("kind") for e in entries}
    assert "insecure_random" in kinds


def test_detect_security_issues_comment_lines_skipped(tmp_path):
    """Plain comment lines without secret patterns are skipped."""
    f = tmp_path / "clean.py"
    f.write_text("# verify = False  (just a comment, not real code)\n")
    entries, scanned = detect_security_issues([str(f)], None, "python")
    assert scanned == 1
    # The comment should be skipped, so no findings
    assert entries == []


def test_detect_security_issues_test_file_downgrades_confidence(tmp_path):
    """Secret format in test file gets medium confidence (not high)."""
    f = tmp_path / "test_config.py"
    f.write_text('key = "AKIAIOSFODNN7EXAMPLE"\n')
    # Mark as production so it's scanned, but tell the scanner it's test
    # Actually: the test_file check uses _is_test_file which checks zone_map
    # We need it scanned (not excluded) but marked as test zone
    # Per _EXCLUDED_SECURITY_ZONES, TEST is excluded, so we need
    # to use a production zone but manually check confidence behavior
    # Instead, test that the scanner itself handles is_test flag:
    from desloppify.engine.detectors.security.scanner import (
        _scan_line_for_security_entries,
    )

    entries_normal = _scan_line_for_security_entries(
        filepath="/app/creds.py",
        line_num=1,
        line='key = "AKIAIOSFODNN7EXAMPLE"',
        is_test=False,
    )
    entries_test = _scan_line_for_security_entries(
        filepath="/tests/test_creds.py",
        line_num=1,
        line='key = "AKIAIOSFODNN7EXAMPLE"',
        is_test=True,
    )
    # Both should find the secret
    assert len(entries_normal) >= 1
    assert len(entries_test) >= 1
    # Test file entries should have medium confidence
    normal_conf = {e.get("confidence") for e in entries_normal}
    test_conf = {e.get("confidence") for e in entries_test}
    assert "high" in normal_conf
    assert "medium" in test_conf
