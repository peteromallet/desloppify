"""Direct tests for TypeScript security helper modules."""

from __future__ import annotations

import desloppify.languages.typescript.detectors.security.entries as entries_mod
import desloppify.languages.typescript.detectors.security.file_checks as file_checks_mod
import desloppify.languages.typescript.detectors.security.line_checks as line_checks_mod


def _kinds(entries: list[dict[str, object]]) -> set[str]:
    return {str(item.get("detail", {}).get("kind", "")) for item in entries}


def test_entries_make_security_entry_wraps_security_rule_payload() -> None:
    entry = entries_mod._make_security_entry(
        "src/app.ts",
        7,
        "eval(userInput)",
        check_id="eval_injection",
        summary="eval use",
        severity="critical",
        confidence="high",
        remediation="remove eval",
    )

    assert entry["file"] == "src/app.ts"
    assert entry["detail"]["kind"] == "eval_injection"
    assert entry["detail"]["line"] == 7
    assert entry["detail"]["severity"] == "critical"


def test_file_checks_cover_edge_auth_json_parse_and_rls_detection() -> None:
    edge_content = (
        "Deno.serve(async (req) => {\n"
        "  const payload = JSON.parse(req.body)\n"
        "  return new Response(payload)\n"
        "})\n"
    )
    edge_lines = edge_content.splitlines()

    assert file_checks_mod._looks_like_edge_handler("/src/functions/handler.ts", edge_content)
    assert not file_checks_mod._looks_like_edge_handler("/src/web/handler.ts", edge_content)
    assert file_checks_mod._extract_handler_body(edge_content) is not None
    assert not file_checks_mod._handler_has_auth_check(edge_content)
    assert file_checks_mod._handler_has_auth_check("requireAuth(user)")

    json_lines = [
        "async function parse() {",
        "  try {",
        "    JSON.parse(a)",
        "  } catch (e) {}",
        "}",
        "function plain() {",
        "  JSON.parse(b)",
        "  // JSON.parse(c)",
        "  JSON.parse(JSON.stringify(d))",
        "}",
    ]
    assert file_checks_mod._is_in_try_scope(json_lines, 3) is True
    assert file_checks_mod._is_in_try_scope(json_lines, 7) is False

    json_entries: list[dict[str, object]] = []
    file_checks_mod._check_json_parse_unguarded("src/parse.ts", json_lines, json_entries)
    assert _kinds(json_entries) == {"json_parse_unguarded"}
    assert json_entries[0]["detail"]["line"] == 7

    sql_content = "CREATE VIEW v AS SELECT 1;\nSELECT 1;"
    sql_lines = sql_content.splitlines()
    rls_entries: list[dict[str, object]] = []
    file_checks_mod._check_rls_bypass("db/schema.sql", sql_content, sql_lines, rls_entries)
    assert _kinds(rls_entries) == {"rls_bypass_views"}

    no_rls_entries: list[dict[str, object]] = []
    file_checks_mod._check_rls_bypass(
        "db/schema.sql",
        "CREATE VIEW v WITH (security_invoker = true) AS SELECT 1;",
        ["CREATE VIEW v WITH (security_invoker = true) AS SELECT 1;"],
        no_rls_entries,
    )
    assert no_rls_entries == []

    combined = file_checks_mod._file_level_security_issues(
        filepath="/src/functions/handler.ts",
        normalized_path="/src/functions/handler.ts",
        lines=edge_lines,
        content=edge_content,
    )
    assert {"edge_function_missing_auth", "json_parse_unguarded"} <= _kinds(combined)

    sql_combined = file_checks_mod._file_level_security_issues(
        filepath="db/schema.sql",
        normalized_path="db/schema.sql",
        lines=sql_lines,
        content=sql_content,
    )
    assert "rls_bypass_views" in _kinds(sql_combined)


def test_json_parse_on_same_line_as_try_catch_is_guarded() -> None:
    lines = [
        "const parse = async () => { try { return JSON.parse(serialized); } catch { return null; } }",
        "try { JSON.parse(first); } catch {} try { JSON.parse(second); } catch (error) {}",
    ]
    entries: list[dict[str, object]] = []

    file_checks_mod._check_json_parse_unguarded("src/parse.ts", lines, entries)

    assert entries == []


def test_json_parse_after_try_or_inside_catch_remains_unguarded() -> None:
    lines = [
        "try { operation(); } catch {} JSON.parse(afterTry);",
        "try { operation(); } catch { JSON.parse(insideCatch); }",
    ]
    entries: list[dict[str, object]] = []

    file_checks_mod._check_json_parse_unguarded("src/parse.ts", lines, entries)

    assert [entry["detail"]["line"] for entry in entries] == [1, 2]


def test_json_parse_scope_ignores_string_syntax_and_nested_arrows() -> None:
    lines = [
        'const brace = "}"; try { JSON.parse(guarded); } catch {}',
        'const example = "try { } catch {}"; JSON.parse(unguarded);',
        "try { const parseLater = () => JSON.parse(callbackValue); } catch {}",
        "try { const noop = () => 0; JSON.parse(afterArrow); } catch {}",
    ]
    entries: list[dict[str, object]] = []

    file_checks_mod._check_json_parse_unguarded("src/parse.ts", lines, entries)

    assert [entry["detail"]["line"] for entry in entries] == [2, 3]


def test_line_checks_report_expected_security_kinds() -> None:
    service_role_lines = [
        "const serviceRole = process.env.SUPABASE_SERVICE_ROLE_KEY",
        "const client = createClient(url, serviceRole)",
    ]
    service_role_issues = line_checks_mod._line_security_issues(
        filepath="src/client.ts",
        normalized_path="/src/client.ts",
        lines=service_role_lines,
        line_num=2,
        line=service_role_lines[1],
        is_server_only=False,
        has_dev_guard=False,
    )
    assert "service_role_on_client" in _kinds(service_role_issues)

    eval_line = "const fn = new Function('a', body)"
    eval_issues = line_checks_mod._line_security_issues(
        filepath="src/eval.ts",
        normalized_path="/src/eval.ts",
        lines=[eval_line],
        line_num=1,
        line=eval_line,
        is_server_only=False,
        has_dev_guard=False,
    )
    assert "eval_injection" in _kinds(eval_issues)

    html_line = "node.innerHTML = payload.dangerouslySetInnerHTML"
    html_issues = line_checks_mod._line_security_issues(
        filepath="src/dom.ts",
        normalized_path="/src/dom.ts",
        lines=[html_line],
        line_num=1,
        line=html_line,
        is_server_only=False,
        has_dev_guard=False,
    )
    assert {"dangerously_set_inner_html", "innerHTML_assignment"} <= _kinds(html_issues)

    dev_cred_line = "const token = import.meta.env.VITE_API_TOKEN"
    dev_cred_issues = line_checks_mod._line_security_issues(
        filepath="src/app.ts",
        normalized_path="/src/app.ts",
        lines=[dev_cred_line],
        line_num=1,
        line=dev_cred_line,
        is_server_only=False,
        has_dev_guard=False,
    )
    assert "dev_credentials_env" in _kinds(dev_cred_issues)

    guarded_dev_issues = line_checks_mod._line_security_issues(
        filepath="src/dev.client.ts",
        normalized_path="/src/dev/client.ts",
        lines=[dev_cred_line],
        line_num=1,
        line=dev_cred_line,
        is_server_only=False,
        has_dev_guard=True,
    )
    assert guarded_dev_issues == []

    redirect_line = "window.location = data.nextUrl"
    redirect_issues = line_checks_mod._line_security_issues(
        filepath="src/redirect.ts",
        normalized_path="/src/redirect.ts",
        lines=[redirect_line],
        line_num=1,
        line=redirect_line,
        is_server_only=False,
        has_dev_guard=False,
    )
    assert "open_redirect" in _kinds(redirect_issues)

    jwt_lines = [
        "const payload = token.split('.')",
        "const decoded = atob(payload[1])",
    ]
    jwt_issues = line_checks_mod._line_security_issues(
        filepath="src/auth.ts",
        normalized_path="/src/auth.ts",
        lines=jwt_lines,
        line_num=2,
        line=jwt_lines[1],
        is_server_only=False,
        has_dev_guard=False,
    )
    assert "unverified_jwt_decode" in _kinds(jwt_issues)
