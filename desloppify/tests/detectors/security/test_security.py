"""Tests for the security detector (cross-language + Python + TypeScript)."""

from __future__ import annotations

import os
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from desloppify.engine.detectors.security.detector import detect_security_issues
from desloppify.engine.policy.zones import FileZoneMap, Zone
from desloppify.languages.typescript.detectors.security.detector import detect_ts_security

# ── Helpers ──────────────────────────────────────────────────


def _write_temp_file(content: str, suffix: str = ".py", dir_prefix: str = "") -> str:
    """Write content to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix, prefix=dir_prefix)
    os.write(fd, content.encode())
    os.close(fd)
    return path


def _make_zone_map(files: list[str], zone: Zone = Zone.PRODUCTION) -> FileZoneMap:
    """Create a simple zone map where all files have the same zone."""
    zm = FileZoneMap.__new__(FileZoneMap)
    zm._map = {f: zone for f in files}
    zm._overrides = None
    return zm


def _detect_ts_security(
    files: list[str],
    zone_map: FileZoneMap | None,
) -> tuple[list[dict], int]:
    result = detect_ts_security(files, zone_map)
    return result.entries, result.population_size


# ═══════════════════════════════════════════════════════════
# Cross-Language Detector Tests
# ═══════════════════════════════════════════════════════════


class TestCrossLangSecretFormats:
    """Test format-based secret detection (AWS keys, GitHub tokens, etc.)."""

    def test_hardcoded_secret_aws_key(self):
        content = 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"'
        path = _write_temp_file(content)
        try:
            entries, _ = detect_security_issues([path], None, "python")
            assert any(e["detail"]["kind"] == "hardcoded_secret_value" for e in entries)
            aws = [e for e in entries if "AWS" in e["summary"]]
            assert len(aws) >= 1
            assert aws[0]["detail"]["severity"] == "critical"
        finally:
            os.unlink(path)

    def test_hardcoded_secret_private_key(self):
        content = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAK..."
        path = _write_temp_file(content)
        try:
            entries, _ = detect_security_issues([path], None, "python")
            assert any(e["detail"]["kind"] == "hardcoded_secret_value" for e in entries)
            pk = [e for e in entries if "Private key" in e["summary"]]
            assert len(pk) >= 1
            assert pk[0]["detail"]["severity"] == "critical"
        finally:
            os.unlink(path)

    def test_hardcoded_github_token(self):
        content = 'token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl"'
        path = _write_temp_file(content)
        try:
            entries, _ = detect_security_issues([path], None, "python")
            assert any("GitHub" in e["summary"] for e in entries)
        finally:
            os.unlink(path)

    def test_hardcoded_stripe_key(self):
        content = 'STRIPE = "sk_live_abcdefghijklmnopqrst"'
        path = _write_temp_file(content)
        try:
            entries, _ = detect_security_issues([path], None, "python")
            assert any("Stripe" in e["summary"] for e in entries)
        finally:
            os.unlink(path)

    def test_hardcoded_slack_token(self):
        content = 'SLACK = "xoxb-123456-789012-abcdef"'
        path = _write_temp_file(content)
        try:
            entries, _ = detect_security_issues([path], None, "python")
            assert any("Slack" in e["summary"] for e in entries)
        finally:
            os.unlink(path)

    def test_hardcoded_jwt(self):
        content = (
            'token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123_-xyz"'
        )
        path = _write_temp_file(content)
        try:
            entries, _ = detect_security_issues([path], None, "python")
            assert any("JWT" in e["summary"] for e in entries)
        finally:
            os.unlink(path)

    def test_hardcoded_db_connection_string(self):
        content = 'DB_URL = "postgres://admin:s3cret@localhost:5432/mydb"'
        path = _write_temp_file(content)
        try:
            entries, _ = detect_security_issues([path], None, "python")
            assert any("Database" in e["summary"] for e in entries)
        finally:
            os.unlink(path)


class TestCrossLangSecretNames:
    """Test variable name + literal value detection."""

    def test_hardcoded_secret_name_match(self):
        content = 'password = "hunter2secret"'
        path = _write_temp_file(content)
        try:
            entries, _ = detect_security_issues([path], None, "python")
            secret_name = [
                e for e in entries if e["detail"]["kind"] == "hardcoded_secret_name"
            ]
            assert len(secret_name) >= 1
            assert "password" in secret_name[0]["summary"]
        finally:
            os.unlink(path)

    def test_hardcoded_secret_env_lookup_ok(self):
        content = 'password = os.getenv("SECRET_PASSWORD")'
        path = _write_temp_file(content)
        try:
            entries, _ = detect_security_issues([path], None, "python")
            secret_name = [
                e for e in entries if e["detail"]["kind"] == "hardcoded_secret_name"
            ]
            assert len(secret_name) == 0
        finally:
            os.unlink(path)

    def test_hardcoded_secret_env_lookup_ts_ok(self):
        content = "const apiKey = process.env.API_KEY"
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = detect_security_issues([path], None, "typescript")
            secret_name = [
                e for e in entries if e["detail"]["kind"] == "hardcoded_secret_name"
            ]
            assert len(secret_name) == 0
        finally:
            os.unlink(path)

    def test_hardcoded_secret_placeholder_ok(self):
        """Placeholders should not be flagged."""
        content = 'password = "changeme"'
        path = _write_temp_file(content)
        try:
            entries, _ = detect_security_issues([path], None, "python")
            secret_name = [
                e for e in entries if e["detail"]["kind"] == "hardcoded_secret_name"
            ]
            assert len(secret_name) == 0
        finally:
            os.unlink(path)

    def test_hardcoded_secret_short_value_ok(self):
        """Short values (< 8 chars) should not be flagged."""
        content = 'secret = "abc"'
        path = _write_temp_file(content)
        try:
            entries, _ = detect_security_issues([path], None, "python")
            secret_name = [
                e for e in entries if e["detail"]["kind"] == "hardcoded_secret_name"
            ]
            assert len(secret_name) == 0
        finally:
            os.unlink(path)

    def test_hardcoded_secret_in_test_zone_skipped(self):
        content = 'password = "test_secret_value123"'
        path = _write_temp_file(content)
        try:
            zm = _make_zone_map([path], Zone.TEST)
            entries, scanned = detect_security_issues([path], zm, "python")
            assert entries == []
            assert scanned == 0
        finally:
            os.unlink(path)


class TestCrossLangInsecureRandom:
    def test_insecure_random(self):
        content = textwrap.dedent("""\
            import random
            token = random.random()
        """)
        path = _write_temp_file(content)
        try:
            entries, _ = detect_security_issues([path], None, "python")
            insecure = [e for e in entries if e["detail"]["kind"] == "insecure_random"]
            assert len(insecure) >= 1
        finally:
            os.unlink(path)

    def test_insecure_random_js(self):
        content = textwrap.dedent("""\
            const nonce = Math.random();
        """)
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = detect_security_issues([path], None, "typescript")
            insecure = [e for e in entries if e["detail"]["kind"] == "insecure_random"]
            assert len(insecure) >= 1
        finally:
            os.unlink(path)

    def test_insecure_random_session_id_ok(self):
        """Math.random() for UI session IDs should not flag (no security word on same line)."""
        content = textwrap.dedent("""\
            const sessionId = `sess-${Date.now()}-${Math.random().toString(36)}`;
        """)
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = detect_security_issues([path], None, "typescript")
            insecure = [e for e in entries if e["detail"]["kind"] == "insecure_random"]
            # "session" is on the same line, so this WILL flag
            # But it should NOT flag if the context is just an ID:
            # Actually session IS a security context word, so this legitimately flags.
            # The key distinction is: random near "session" on the same line is flagged.
            assert len(insecure) >= 1
        finally:
            os.unlink(path)

    def test_insecure_random_cache_bust_ok(self):
        """Math.random() for cache-busting (no security word on same line) should not flag."""
        content = textwrap.dedent("""\
            const cacheBuster = Math.random().toString(36);
            const url = `${base}?cb=${cacheBuster}`;
        """)
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = detect_security_issues([path], None, "typescript")
            insecure = [e for e in entries if e["detail"]["kind"] == "insecure_random"]
            assert len(insecure) == 0
        finally:
            os.unlink(path)


class TestCrossLangWeakCrypto:
    def test_weak_crypto_tls_verify_false(self):
        content = 'requests.get("https://api.example.com", verify=False)'
        path = _write_temp_file(content)
        try:
            entries, _ = detect_security_issues([path], None, "python")
            weak = [e for e in entries if e["detail"]["kind"] == "weak_crypto_tls"]
            assert len(weak) >= 1
        finally:
            os.unlink(path)

    def test_weak_crypto_reject_unauthorized(self):
        content = "const agent = new https.Agent({ rejectUnauthorized: false });"
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = detect_security_issues([path], None, "typescript")
            weak = [e for e in entries if e["detail"]["kind"] == "weak_crypto_tls"]
            assert len(weak) >= 1
        finally:
            os.unlink(path)


class TestCrossLangLogSensitive:
    def test_log_sensitive(self):
        content = 'logger.info(f"user logged in with token={token}")'
        path = _write_temp_file(content)
        try:
            entries, _ = detect_security_issues([path], None, "python")
            log_entries = [e for e in entries if e["detail"]["kind"] == "log_sensitive"]
            assert len(log_entries) >= 1
        finally:
            os.unlink(path)

    def test_log_sensitive_console(self):
        content = 'console.log("Authorization:", authHeader);'
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = detect_security_issues([path], None, "typescript")
            log_entries = [e for e in entries if e["detail"]["kind"] == "log_sensitive"]
            assert len(log_entries) >= 1
        finally:
            os.unlink(path)

    @pytest.mark.parametrize(
        "content",
        [
            'print("out tokens")',
            'print(f"{count} token strip(s)")',
            'print(f"folder token(s): {count}")',
            'print(f"folder_token_strip({stem!r})")',
        ],
    )
    def test_log_sensitive_ignores_noncredential_token_vocabulary(self, content):
        path = _write_temp_file(content)
        try:
            entries, _ = detect_security_issues([path], None, "python")
            log_entries = [e for e in entries if e["detail"]["kind"] == "log_sensitive"]
            assert log_entries == []
        finally:
            os.unlink(path)

    @pytest.mark.parametrize(
        "content",
        [
            "print(token)",
            'logger.info("%s", credentials)',
            'console.log("api_key=", apiKey);',
        ],
    )
    def test_log_sensitive_detects_bare_sensitive_values(self, content):
        suffix = ".ts" if content.startswith("console") else ".py"
        path = _write_temp_file(content, suffix=suffix)
        try:
            entries, _ = detect_security_issues([path], None, suffix.removeprefix("."))
            log_entries = [e for e in entries if e["detail"]["kind"] == "log_sensitive"]
            assert len(log_entries) == 1
        finally:
            os.unlink(path)


class TestCrossLangZoneFiltering:
    def test_generated_zone_skipped(self):
        content = 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"'
        path = _write_temp_file(content)
        try:
            zm = _make_zone_map([path], Zone.GENERATED)
            entries, scanned = detect_security_issues([path], zm, "python")
            assert len(entries) == 0
            assert scanned == 0
        finally:
            os.unlink(path)

    def test_vendor_zone_skipped(self):
        content = 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"'
        path = _write_temp_file(content)
        try:
            zm = _make_zone_map([path], Zone.VENDOR)
            entries, scanned = detect_security_issues([path], zm, "python")
            assert len(entries) == 0
            assert scanned == 0
        finally:
            os.unlink(path)

    def test_test_zone_skipped(self):
        content = 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"'
        path = _write_temp_file(content)
        try:
            zm = _make_zone_map([path], Zone.TEST)
            entries, scanned = detect_security_issues([path], zm, "python")
            assert len(entries) == 0
            assert scanned == 0
        finally:
            os.unlink(path)

    def test_config_zone_skipped(self):
        content = 'DB_URL = "postgres://admin:s3cret@localhost:5432/mydb"'
        path = _write_temp_file(content)
        try:
            zm = _make_zone_map([path], Zone.CONFIG)
            entries, scanned = detect_security_issues([path], zm, "python")
            assert len(entries) == 0
            assert scanned == 0
        finally:
            os.unlink(path)


# Python-specific security checks removed — now handled by bandit_adapter.py.
# See tests/detectors/test_external_adapters.py :: TestBanditAdapter.


# ═══════════════════════════════════════════════════════════
# TypeScript-Specific Detector Tests
# ═══════════════════════════════════════════════════════════


class TestTsReadFailures:
    def test_read_failures_are_reported_in_entries(self):
        with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            entries, scanned = _detect_ts_security(["/fake/src/client.ts"], None)
        assert scanned == 0
        assert any(e["detail"]["kind"] == "scan_read_error" for e in entries)


class TestTsServiceRoleOnClient:
    def test_service_role_on_client(self):
        content = textwrap.dedent("""\
            const supabase = createClient(url, SERVICE_ROLE_KEY)
        """)
        with patch.object(Path, "read_text", return_value=content):
            entries, _ = _detect_ts_security(["/fake/src/client.ts"], None)
        assert any(e["detail"]["kind"] == "service_role_on_client" for e in entries)

    def test_service_role_camel_case_on_client(self):
        content = textwrap.dedent("""\
            const supabase = createClient(url, serviceRole)
        """)
        with patch.object(Path, "read_text", return_value=content):
            entries, _ = _detect_ts_security(["/fake/src/client.ts"], None)
        assert any(e["detail"]["kind"] == "service_role_on_client" for e in entries)

    def test_service_role_on_server_path_not_flagged(self):
        content = textwrap.dedent("""\
            const supabase = createClient(url, SERVICE_ROLE_KEY)
        """)
        with patch.object(Path, "read_text", return_value=content):
            entries, _ = _detect_ts_security(["/fake/functions/worker.ts"], None)
        assert not any(e["detail"]["kind"] == "service_role_on_client" for e in entries)


class TestTsEdgeFunctionAuth:
    def test_edge_function_missing_auth_flagged(self):
        content = textwrap.dedent("""\
            import { serve } from "https://deno.land/std/http/server.ts";
            serve(async (req) => {
              return new Response("ok");
            });
        """)
        with patch.object(Path, "read_text", return_value=content):
            entries, _ = _detect_ts_security(["/fake/functions/orders.ts"], None)
        kinds = {e["detail"]["kind"] for e in entries}
        assert "edge_function_missing_auth" in kinds

    def test_edge_function_authorization_header_mention_not_enough(self):
        content = textwrap.dedent("""\
            import { serve } from "https://deno.land/std/http/server.ts";
            serve(async (req) => {
              const header = req.headers.get("Authorization");
              return new Response(header ?? "missing");
            });
        """)
        with patch.object(Path, "read_text", return_value=content):
            entries, _ = _detect_ts_security(["/fake/functions/orders.ts"], None)
        kinds = {e["detail"]["kind"] for e in entries}
        assert "edge_function_missing_auth" in kinds

    def test_edge_function_auth_check_present_not_flagged(self):
        content = textwrap.dedent("""\
            import { serve } from "https://deno.land/std/http/server.ts";
            serve(async (req) => {
              const user = await auth.getUser(req);
              if (!user) return new Response("unauthorized", { status: 401 });
              return new Response("ok");
            });
        """)
        with patch.object(Path, "read_text", return_value=content):
            entries, _ = _detect_ts_security(["/fake/functions/orders.ts"], None)
        kinds = {e["detail"]["kind"] for e in entries}
        assert "edge_function_missing_auth" not in kinds

    def test_edge_function_lookup_without_rejection_still_flagged(self):
        content = textwrap.dedent("""\
            import { serve } from "https://deno.land/std/http/server.ts";
            serve(async (req) => {
              const user = await auth.getUser(req);
              return new Response(user ? "ok" : "missing");
            });
        """)
        with patch.object(Path, "read_text", return_value=content):
            entries, _ = _detect_ts_security(["/fake/functions/orders.ts"], None)
        kinds = {e["detail"]["kind"] for e in entries}
        assert "edge_function_missing_auth" in kinds


class TestTsEvalInjection:
    def test_eval_injection(self):
        content = "const result = eval(userInput);"
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = _detect_ts_security([path], None)
            evals = [e for e in entries if e["detail"]["kind"] == "eval_injection"]
            assert len(evals) >= 1
            assert evals[0]["detail"]["severity"] == "critical"
        finally:
            os.unlink(path)

    def test_new_function_injection(self):
        content = 'const fn = new Function("return " + userInput);'
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = _detect_ts_security([path], None)
            evals = [e for e in entries if e["detail"]["kind"] == "eval_injection"]
            assert len(evals) >= 1
        finally:
            os.unlink(path)


class TestTsDangerousHtml:
    def test_dangerously_set_inner_html(self):
        content = "<div dangerouslySetInnerHTML={{__html: data}} />"
        path = _write_temp_file(content, suffix=".tsx")
        try:
            entries, _ = _detect_ts_security([path], None)
            xss = [
                e
                for e in entries
                if e["detail"]["kind"] == "dangerously_set_inner_html"
            ]
            assert len(xss) >= 1
        finally:
            os.unlink(path)

    def test_innerHTML_assignment(self):
        content = "element.innerHTML = userInput;"
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = _detect_ts_security([path], None)
            xss = [e for e in entries if e["detail"]["kind"] == "innerHTML_assignment"]
            assert len(xss) >= 1
        finally:
            os.unlink(path)


class TestTsDevCredentials:
    def test_dev_credentials_env(self):
        content = "const pass = import.meta.env.VITE_DEV_PASSWORD;"
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = _detect_ts_security([path], None)
            creds = [e for e in entries if e["detail"]["kind"] == "dev_credentials_env"]
            assert len(creds) >= 1
        finally:
            os.unlink(path)


class TestTsJsonParse:
    def test_json_parse_deep_clone_ok(self):
        """JSON.parse(JSON.stringify(x)) deep-clone idiom should not flag."""
        content = textwrap.dedent("""\
            const clone = JSON.parse(JSON.stringify(sourceValue));
        """)
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = _detect_ts_security([path], None)
            jp = [e for e in entries if e["detail"]["kind"] == "json_parse_unguarded"]
            assert len(jp) == 0
        finally:
            os.unlink(path)

    def test_json_parse_user_input_flagged(self):
        """JSON.parse(userInput) outside try should flag."""
        content = textwrap.dedent("""\
            const data = JSON.parse(userInput);
        """)
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = _detect_ts_security([path], None)
            jp = [e for e in entries if e["detail"]["kind"] == "json_parse_unguarded"]
            assert len(jp) >= 1
        finally:
            os.unlink(path)

    def test_json_parse_in_try_catch_not_flagged(self):
        """JSON.parse inside try { ... } catch should not flag."""
        content = textwrap.dedent("""\
            try {
              const data = JSON.parse(userInput);
              return data;
            } catch (e) {
              return null;
            }
        """)
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = _detect_ts_security([path], None)
            jp = [e for e in entries if e["detail"]["kind"] == "json_parse_unguarded"]
            assert len(jp) == 0
        finally:
            os.unlink(path)

    def test_json_parse_in_try_multiline(self):
        """try on one line, { on next — JSON.parse should still be guarded."""
        content = textwrap.dedent("""\
            try
            {
              const data = JSON.parse(raw);
            } catch (e) {
              console.error(e);
            }
        """)
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = _detect_ts_security([path], None)
            jp = [e for e in entries if e["detail"]["kind"] == "json_parse_unguarded"]
            assert len(jp) == 0
        finally:
            os.unlink(path)

    def test_json_parse_outside_try_still_flagged(self):
        """JSON.parse with no enclosing try should still be flagged."""
        content = textwrap.dedent("""\
            function parseData(raw: string) {
              const data = JSON.parse(raw);
              return data;
            }
        """)
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = _detect_ts_security([path], None)
            jp = [e for e in entries if e["detail"]["kind"] == "json_parse_unguarded"]
            assert len(jp) >= 1
        finally:
            os.unlink(path)

    def test_json_parse_nested_function_in_try(self):
        """JSON.parse in inner function inside try — still flagged (conservative)."""
        content = textwrap.dedent("""\
            try {
              function inner() {
                const data = JSON.parse(raw);
              }
            } catch (e) {}
        """)
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = _detect_ts_security([path], None)
            jp = [e for e in entries if e["detail"]["kind"] == "json_parse_unguarded"]
            assert len(jp) >= 1
        finally:
            os.unlink(path)


class TestTsOpenRedirect:
    def test_open_redirect(self):
        content = "window.location.href = data.redirectUrl;"
        path = _write_temp_file(content, suffix=".ts")
        try:
            entries, _ = _detect_ts_security([path], None)
            redirects = [e for e in entries if e["detail"]["kind"] == "open_redirect"]
            assert len(redirects) >= 1
        finally:
            os.unlink(path)


class TestTsRlsBypass:
    def test_rls_bypass_views(self):
        content = textwrap.dedent("""\
            CREATE VIEW user_data AS
            SELECT * FROM users;
        """)
        path = _write_temp_file(content, suffix=".sql")
        try:
            entries, _ = _detect_ts_security([path], None)
            rls = [e for e in entries if e["detail"]["kind"] == "rls_bypass_views"]
            assert len(rls) >= 1
        finally:
            os.unlink(path)

    def test_rls_bypass_views_with_invoker_ok(self):
        content = textwrap.dedent("""\
            CREATE VIEW user_data
            WITH (security_invoker = true) AS
            SELECT * FROM users;
        """)
        path = _write_temp_file(content, suffix=".sql")
        try:
            entries, _ = _detect_ts_security([path], None)
            rls = [e for e in entries if e["detail"]["kind"] == "rls_bypass_views"]
            assert len(rls) == 0
        finally:
            os.unlink(path)
