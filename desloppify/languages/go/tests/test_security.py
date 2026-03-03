"""Tests for desloppify.languages.go.detectors.security — Go security detection."""

from __future__ import annotations

from pathlib import Path

from desloppify.languages.go.detectors.security import detect_go_security


def _write(tmp_path: Path, name: str, content: str) -> str:
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    return str(f)


def _detect(tmp_path: Path, filename: str, content: str) -> list[dict]:
    filepath = _write(tmp_path, filename, content)
    entries, _ = detect_go_security([filepath], zone_map=None)
    return entries


# ── unsafe.Pointer ──────────────────────────────────────────


def test_unsafe_pointer(tmp_path):
    entries = _detect(
        tmp_path,
        "hack.go",
        'package hack\n\nimport "unsafe"\n\nfunc f() {\n    p := unsafe.Pointer(nil)\n    _ = p\n}\n',
    )
    ids = {e["detail"]["kind"] for e in entries}
    assert "unsafe_pointer" in ids


# ── SQL injection ───────────────────────────────────────────


def test_sql_injection_sprintf(tmp_path):
    entries = _detect(
        tmp_path,
        "db.go",
        'package db\n\nfunc f(db *sql.DB, name string) {\n    db.Query(fmt.Sprintf("SELECT * FROM users WHERE name = \'%s\'", name))\n}\n',
    )
    ids = {e["detail"]["kind"] for e in entries}
    assert "sql_injection" in ids


def test_sql_injection_concat(tmp_path):
    entries = _detect(
        tmp_path,
        "db.go",
        'package db\n\nfunc f(db *sql.DB, name string) {\n    db.Query("SELECT * FROM users WHERE name = " + name)\n}\n',
    )
    ids = {e["detail"]["kind"] for e in entries}
    assert "sql_injection" in ids


# ── Weak hash ──────────────────────────────────────────────


def test_weak_hash_md5(tmp_path):
    entries = _detect(
        tmp_path,
        "hash.go",
        "package hash\n\nfunc f() {\n    h := md5.New()\n    _ = h\n}\n",
    )
    ids = {e["detail"]["kind"] for e in entries}
    assert "weak_hash" in ids


def test_weak_hash_sha1(tmp_path):
    entries = _detect(
        tmp_path,
        "hash.go",
        "package hash\n\nfunc f() {\n    h := sha1.Sum(nil)\n    _ = h\n}\n",
    )
    ids = {e["detail"]["kind"] for e in entries}
    assert "weak_hash" in ids


# ── HTTP without TLS ────────────────────────────────────────


def test_http_no_tls(tmp_path):
    entries = _detect(
        tmp_path,
        "server.go",
        'package main\n\nfunc main() {\n    http.ListenAndServe(":8080", nil)\n}\n',
    )
    ids = {e["detail"]["kind"] for e in entries}
    assert "http_no_tls" in ids


# ── Command injection ──────────────────────────────────────


def test_command_injection_variable(tmp_path):
    entries = _detect(
        tmp_path,
        "exec.go",
        "package exec\n\nfunc f(cmd string) {\n    exec.Command(cmd)\n}\n",
    )
    ids = {e["detail"]["kind"] for e in entries}
    assert "command_injection" in ids


def test_command_injection_literal_not_flagged(tmp_path):
    entries = _detect(
        tmp_path,
        "exec.go",
        'package exec\n\nfunc f() {\n    exec.Command("ls", "-la")\n}\n',
    )
    cmd_entries = [e for e in entries if e["detail"]["kind"] == "command_injection"]
    assert not cmd_entries


# ── Hardcoded credentials ──────────────────────────────────


def test_hardcoded_credentials(tmp_path):
    entries = _detect(
        tmp_path,
        "auth.go",
        'package auth\n\nfunc f() {\n    password := "supersecretpassword123"\n    _ = password\n}\n',
    )
    ids = {e["detail"]["kind"] for e in entries}
    assert "hardcoded_credentials" in ids


# ── Insecure random ────────────────────────────────────────


def test_insecure_random_in_crypto_context(tmp_path):
    entries = _detect(
        tmp_path,
        "token.go",
        'package token\n\nimport "math/rand"\n\nfunc GenerateToken() int {\n    return rand.Int()\n}\n',
    )
    ids = {e["detail"]["kind"] for e in entries}
    assert "insecure_random" in ids


# ── Zone filtering ─────────────────────────────────────────


def test_test_files_skipped_with_zone_map(tmp_path):
    from desloppify.engine.policy.zones import FileZoneMap, Zone, ZoneRule

    filepath = _write(
        tmp_path,
        "auth_test.go",
        'package auth\n\nfunc f() {\n    password := "testpassword1234"\n    _ = password\n}\n',
    )
    zone_map = FileZoneMap(
        [filepath],
        [ZoneRule(Zone.TEST, ["_test.go"])],
        rel_fn=lambda p: p,
    )
    entries, scanned = detect_go_security([filepath], zone_map=zone_map)
    assert scanned == 0
    assert not entries


# ── Clean code ─────────────────────────────────────────────


def test_clean_code_no_findings(tmp_path):
    entries = _detect(
        tmp_path,
        "clean.go",
        "package clean\n\nfunc Add(a, b int) int {\n    return a + b\n}\n",
    )
    assert not entries


def test_comment_lines_skipped(tmp_path):
    entries = _detect(
        tmp_path,
        "lib.go",
        "package lib\n\n// unsafe.Pointer is dangerous\nfunc f() {}\n",
    )
    assert not entries
