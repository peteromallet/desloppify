"""Focused unit tests for security.rules helpers."""

from __future__ import annotations

from desloppify.engine.detectors.patterns.security import (
    _looks_like_non_secret_value,
    is_placeholder,
)
from desloppify.engine.detectors.security import rules as rules_mod


def test_make_security_entry_builds_stable_shape():
    rule = rules_mod.SecurityRule(
        check_id="hardcoded_secret",
        summary="Hardcoded secret found",
        severity="high",
        confidence="high",
        remediation="Use env vars",
    )

    entry = rules_mod.make_security_entry(
        filepath="src/app/module.py",
        line=14,
        content="password = 'supersecret123'",
        rule=rule,
    )

    assert entry["file"] == "src/app/module.py"
    assert entry["name"].startswith("security::hardcoded_secret::")
    assert entry["detail"]["line"] == 14
    assert entry["detail"]["kind"] == "hardcoded_secret"
    assert entry["detail"]["remediation"] == "Use env vars"


def test_secret_format_entries_set_test_confidence_medium():
    entries = rules_mod._secret_format_entries(
        filepath="src/security.py",
        line_num=2,
        line='aws_key = "AKIA1234567890ABCDEF"',
        is_test=True,
    )

    assert len(entries) == 1
    assert entries[0]["confidence"] == "medium"
    assert entries[0]["detail"]["kind"] == "hardcoded_secret_value"


def test_secret_name_entries_skip_placeholder_and_flag_real_secret():
    placeholder_entries = rules_mod._secret_name_entries(
        filepath="src/config.py",
        line_num=1,
        line='api_key = "changeme"',
        is_test=False,
    )
    real_entries = rules_mod._secret_name_entries(
        filepath="src/config.py",
        line_num=2,
        line='api_key = "supersecret123"',
        is_test=False,
    )

    assert placeholder_entries == []
    assert len(real_entries) == 1
    assert "api_key" in real_entries[0]["summary"]
    assert real_entries[0]["detail"]["kind"] == "hardcoded_secret_name"


def test_insecure_random_entries_require_security_context():
    assert rules_mod._insecure_random_entries(
        filepath="src/nonce.py",
        line_num=4,
        line="value = random.random()",
    ) == []

    issues = rules_mod._insecure_random_entries(
        filepath="src/nonce.py",
        line_num=5,
        line="nonce = random.random()",
    )
    assert len(issues) == 1
    assert issues[0]["detail"]["kind"] == "insecure_random"


def test_weak_crypto_entries_detect_verify_false():
    issues = rules_mod._weak_crypto_entries(
        filepath="src/http.py",
        line_num=9,
        line="response = requests.get(url, verify=False)",
    )

    assert len(issues) == 1
    assert issues[0]["detail"]["kind"] == "weak_crypto_tls"
    assert issues[0]["detail"]["severity"] == "high"


def test_sensitive_log_entries_detect_secret_logs():
    issues = rules_mod._sensitive_log_entries(
        filepath="src/logging.py",
        line_num=11,
        line='logger.info("token=%s", token)',
    )

    assert len(issues) == 1
    assert issues[0]["detail"]["kind"] == "log_sensitive"


def test_sensitive_log_entries_ignore_noncredential_token_vocabulary():
    issues = rules_mod._sensitive_log_entries(
        filepath="src/report.py",
        line_num=12,
        line='print(f"{count} token strip(s)")',
    )

    assert issues == []


# ── _looks_like_non_secret_value heuristic ────────────────


class TestLooksLikeNonSecretValue:
    """Regression tests for issue #496: false positives on non-secret values."""

    def test_field_name_with_underscores(self):
        assert _looks_like_non_secret_value("token_usage") is True

    def test_dict_key_with_underscores(self):
        assert _looks_like_non_secret_value("transition_token") is True

    def test_sentinel_with_spaces(self):
        assert _looks_like_non_secret_value(" flow ticket_flow start ") is True

    def test_prefix_with_at_sign(self):
        assert _looks_like_non_secret_value("agent_workspace@") is True

    def test_empty_string(self):
        assert _looks_like_non_secret_value("") is True

    def test_real_secret_mixed_case(self):
        assert _looks_like_non_secret_value("aB3kF9mZ2xQ7wR") is False

    def test_real_secret_with_prefix(self):
        assert _looks_like_non_secret_value("sk-abc123XYZ789def456") is False

    def test_password_like_value(self):
        """A value like 'supersecret123' should NOT be skipped."""
        assert _looks_like_non_secret_value("supersecret123") is False

    def test_config_key_field_name(self):
        assert _looks_like_non_secret_value("some_config_key") is True

    def test_url_path_lowercase(self):
        assert _looks_like_non_secret_value("api/v1/tokens") is True

    def test_label_with_colon(self):
        assert _looks_like_non_secret_value("auth:token_key") is True


# ── is_placeholder integration with new heuristic ─────────


class TestIsPlaceholderNonSecretValues:
    """Issue #496: is_placeholder should catch non-secret field names."""

    def test_field_name_token_usage(self):
        assert is_placeholder("token_usage") is True

    def test_field_name_transition_token(self):
        assert is_placeholder("transition_token") is True

    def test_sentinel_marker(self):
        assert is_placeholder(" flow ticket_flow start ") is True

    def test_autocomplete_prefix(self):
        assert is_placeholder("agent_workspace@") is True

    def test_real_secret_still_flagged(self):
        assert is_placeholder("supersecret123") is False

    def test_mixed_case_secret_still_flagged(self):
        assert is_placeholder("aB3kF9mZ2xQ7wR") is False

    def test_existing_placeholders_still_work(self):
        assert is_placeholder("changeme") is True
        assert is_placeholder("") is True
        assert is_placeholder("xxx") is True
        assert is_placeholder("<your-key>") is True
        assert is_placeholder("${SECRET}") is True

    def test_short_values_still_skipped(self):
        assert is_placeholder("abc") is True
        assert is_placeholder("1234567") is True


# ── _secret_name_entries with false-positive values ───────


class TestSecretNameFalsePositives:
    """Issue #496: end-to-end regression for _secret_name_entries."""

    def test_token_usage_field_name_not_flagged(self):
        entries = rules_mod._secret_name_entries(
            filepath="src/constants.py",
            line_num=1,
            line='TOKEN_USAGE = "token_usage"',
            is_test=False,
        )
        assert entries == []

    def test_transition_token_key_not_flagged(self):
        entries = rules_mod._secret_name_entries(
            filepath="src/constants.py",
            line_num=2,
            line='TRANSITION_TOKEN_KEY = "transition_token"',
            is_test=False,
        )
        assert entries == []

    def test_sentinel_marker_not_flagged(self):
        entries = rules_mod._secret_name_entries(
            filepath="src/flow.py",
            line_num=3,
            line='_START_NEW_FLOW_TOKEN = " flow ticket_flow start "',
            is_test=False,
        )
        assert entries == []

    def test_autocomplete_prefix_not_flagged(self):
        entries = rules_mod._secret_name_entries(
            filepath="src/autocomplete.py",
            line_num=4,
            line='AGENT_WORKSPACE_AUTOCOMPLETE_TOKEN_PREFIX = "agent_workspace@"',
            is_test=False,
        )
        assert entries == []

    def test_real_secret_still_detected(self):
        entries = rules_mod._secret_name_entries(
            filepath="src/config.py",
            line_num=5,
            line='api_key = "supersecret123"',
            is_test=False,
        )
        assert len(entries) == 1
        assert entries[0]["detail"]["kind"] == "hardcoded_secret_name"

