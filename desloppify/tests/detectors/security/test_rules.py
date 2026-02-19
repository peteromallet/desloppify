"""Focused unit tests for security.rules helpers."""

from __future__ import annotations

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

    findings = rules_mod._insecure_random_entries(
        filepath="src/nonce.py",
        line_num=5,
        line="nonce = random.random()",
    )
    assert len(findings) == 1
    assert findings[0]["detail"]["kind"] == "insecure_random"


def test_weak_crypto_entries_detect_verify_false():
    findings = rules_mod._weak_crypto_entries(
        filepath="src/http.py",
        line_num=9,
        line="response = requests.get(url, verify=False)",
    )

    assert len(findings) == 1
    assert findings[0]["detail"]["kind"] == "weak_crypto_tls"
    assert findings[0]["detail"]["severity"] == "high"


def test_sensitive_log_entries_detect_secret_logs():
    findings = rules_mod._sensitive_log_entries(
        filepath="src/logging.py",
        line_num=11,
        line='logger.info("token=%s", token)',
    )

    assert len(findings) == 1
    assert findings[0]["detail"]["kind"] == "log_sensitive"

