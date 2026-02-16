"""Tests for desloppify.lang.typescript.detectors.smells — TS/React code smell detection."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _set_project_root(tmp_path, monkeypatch):
    """Point PROJECT_ROOT at the tmp directory so file resolution works.

    Must patch both utils and smells modules because smells.py binds
    PROJECT_ROOT at import time via `from ....utils import PROJECT_ROOT`.
    """
    monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))
    import desloppify.utils as utils_mod
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
    import desloppify.lang.typescript.detectors.smells as smells_mod
    monkeypatch.setattr(smells_mod, "PROJECT_ROOT", tmp_path)
    # Clear the lru_cache so file discovery uses the new PROJECT_ROOT
    utils_mod._find_source_files_cached.cache_clear()


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# ── detect_smells: regex-based smells ────────────────────────


def test_detect_any_type(tmp_path):
    """Detects explicit `any` type annotations."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", "const x: any = 5;\nconst y: string = 'ok';\n")
    entries, total = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "any_type" in ids
    any_entry = next(e for e in entries if e["id"] == "any_type")
    assert any_entry["count"] == 1


def test_detect_ts_ignore(tmp_path):
    """Detects @ts-ignore and @ts-expect-error comments."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", (
        "// @ts-ignore\nconst a = 1;\n"
        "// @ts-expect-error\nconst b = 2;\n"
    ))
    entries, _ = detect_smells(tmp_path)
    ts_ignore = next(e for e in entries if e["id"] == "ts_ignore")
    assert ts_ignore["count"] == 2


def test_detect_ts_nocheck(tmp_path):
    """Detects @ts-nocheck directive."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", "// @ts-nocheck\nconst a: any = 'hello';\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "ts_nocheck" in ids


def test_detect_empty_catch(tmp_path):
    """Detects empty catch blocks."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", "try { foo(); } catch (e) { }\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "empty_catch" in ids


def test_detect_non_null_assertion(tmp_path):
    """Detects non-null assertions (variable!.property)."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", "const x = obj!.value;\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "non_null_assert" in ids


def test_detect_hardcoded_color(tmp_path):
    """Detects hardcoded hex color values."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", "const style = { color: '#ff0000' };\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "hardcoded_color" in ids


def test_detect_hardcoded_rgb(tmp_path):
    """Detects hardcoded rgb/rgba color values."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", "const bg = rgba(255, 0, 0, 1);\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "hardcoded_rgb" in ids


def test_detect_magic_number(tmp_path):
    """Detects magic numbers (>1000 in logic)."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", "if (count >= 9999) { doSomething(); }\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "magic_number" in ids


def test_detect_hardcoded_url(tmp_path):
    """Detects hardcoded URLs in source code."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", "const endpoint = 'https://api.example.com/v1';\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "hardcoded_url" in ids


def test_hardcoded_url_skips_module_constants(tmp_path):
    """Module-level UPPER_CASE constants with URLs should not be flagged."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "config.ts", "export const API_URL = 'https://api.example.com/v1';\n")
    entries, _ = detect_smells(tmp_path)
    url_entries = [e for e in entries if e["id"] == "hardcoded_url"]
    assert len(url_entries) == 0


def test_detect_todo_fixme(tmp_path):
    """Detects TODO/FIXME/HACK/XXX comments."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", (
        "// TODO: fix this\n"
        "// FIXME: broken\n"
        "// HACK: workaround\n"
        "const x = 1;\n"
    ))
    entries, _ = detect_smells(tmp_path)
    todo_entry = next(e for e in entries if e["id"] == "todo_fixme")
    assert todo_entry["count"] == 3


def test_detect_as_any_cast(tmp_path):
    """Detects `as any` type casts."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", "const val = someObj as any;\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "as_any_cast" in ids


def test_detect_sort_no_comparator(tmp_path):
    """Detects .sort() calls without a comparator."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", "const sorted = items.sort();\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "sort_no_comparator" in ids


def test_detect_debug_tag(tmp_path):
    """Detects vestigial debug tags like '[DEBUG_TAG] message'."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", "console.log('[MY_DEBUG] something happened');\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "debug_tag" in ids


def test_detect_workaround_tag(tmp_path):
    """Detects workaround tags like // [PascalCaseTag]."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", "// [WorkaroundForBug] this is a hack\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "workaround_tag" in ids


def test_detect_voided_symbol(tmp_path):
    """Detects dead code via void symbol suppression."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", "void unusedVar;\nvoid anotherOne;\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "voided_symbol" in ids
    voided = next(e for e in entries if e["id"] == "voided_symbol")
    assert voided["count"] == 2


# ── detect_smells: multi-line smells ─────────────────────────


def test_detect_async_no_await(tmp_path):
    """Detects async functions without any await."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", (
        "async function fetchData() {\n"
        "  const x = 1;\n"
        "  return x;\n"
        "}\n"
    ))
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "async_no_await" in ids


def test_async_with_await_not_flagged(tmp_path):
    """Async functions that do use await should not be flagged."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "ok.ts", (
        "async function fetchData() {\n"
        "  const data = await fetch('/api');\n"
        "  return data;\n"
        "}\n"
    ))
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "async_no_await" not in ids


def test_detect_console_error_no_throw(tmp_path):
    """Detects console.error not followed by throw or return."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", (
        "function handle() {\n"
        "  console.error('something went wrong');\n"
        "  doOtherStuff();\n"
        "  moreStuff();\n"
        "  evenMoreStuff();\n"
        "}\n"
    ))
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "console_error_no_throw" in ids


def test_console_error_with_throw_not_flagged(tmp_path):
    """console.error followed by throw should not be flagged."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "ok.ts", (
        "function handle() {\n"
        "  console.error('fail');\n"
        "  throw new Error('fail');\n"
        "}\n"
    ))
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "console_error_no_throw" not in ids


def test_detect_swallowed_error(tmp_path):
    """Detects catch blocks that only console.log/warn/error (swallowed errors)."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", (
        "try {\n"
        "  riskyOp();\n"
        "} catch (err) {\n"
        "  console.error(err);\n"
        "}\n"
    ))
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "swallowed_error" in ids


def test_detect_dead_useeffect(tmp_path):
    """Detects useEffect with empty body."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.tsx", (
        "useEffect(() => {\n"
        "  // nothing here\n"
        "}, [dep]);\n"
    ))
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "dead_useeffect" in ids


def test_detect_empty_if_chain(tmp_path):
    """Detects if/else chains with all empty branches."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", (
        "if (a) { }\n"
        "else if (b) { }\n"
        "else { }\n"
    ))
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "empty_if_chain" in ids


def test_detect_window_global(tmp_path):
    """Detects window.__* assignments (global escape hatches)."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", "window.__myGlobal = 'test';\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "window_global" in ids


def test_detect_monster_function(tmp_path):
    """Detects functions exceeding 150 LOC."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    body_lines = "\n".join(f"  const line{i} = {i};" for i in range(160))
    _write(tmp_path, "bad.ts", (
        f"function bigFunction() {{\n{body_lines}\n}}\n"
    ))
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "monster_function" in ids


def test_detect_dead_function(tmp_path):
    """Detects functions with empty body or only return null."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", (
        "function emptyFunc() {\n}\n"
        "function nullFunc() {\n  return null;\n}\n"
    ))
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "dead_function" in ids
    dead = next(e for e in entries if e["id"] == "dead_function")
    assert dead["count"] == 2


def test_detect_catch_return_default(tmp_path):
    """Detects catch blocks returning default objects (silent failure)."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", (
        "try {\n"
        "  return getData();\n"
        "} catch (e) {\n"
        "  return { success: false, data: null, error: null };\n"
        "}\n"
    ))
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "catch_return_default" in ids


# ── Filtering behavior ───────────────────────────────────────


def test_node_modules_excluded(tmp_path):
    """Files under node_modules are skipped."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "bad.ts").write_text("const x: any = 1;\n")
    entries, _ = detect_smells(tmp_path)
    # The any_type should not appear because node_modules is excluded
    any_entries = [e for e in entries if e["id"] == "any_type"]
    assert len(any_entries) == 0


def test_dts_files_excluded(tmp_path):
    """Declaration files (.d.ts) are skipped."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "types.d.ts", "declare const x: any;\n")
    entries, _ = detect_smells(tmp_path)
    any_entries = [e for e in entries if e["id"] == "any_type"]
    assert len(any_entries) == 0


def test_smells_in_block_comments_not_flagged(tmp_path):
    """Code patterns inside block comments should not be detected."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "ok.ts", (
        "/* This is a block comment\n"
        "   const x: any = 1;\n"
        "*/\n"
        "const y: string = 'clean';\n"
    ))
    entries, _ = detect_smells(tmp_path)
    any_entries = [e for e in entries if e["id"] == "any_type"]
    assert len(any_entries) == 0


def test_smells_in_string_literals_not_flagged(tmp_path):
    """Patterns inside string literals should not be detected."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "ok.ts", "const msg = 'This is: any type of message';\n")
    entries, _ = detect_smells(tmp_path)
    any_entries = [e for e in entries if e["id"] == "any_type"]
    assert len(any_entries) == 0


def test_clean_file_no_smells(tmp_path):
    """A clean file should produce no smell entries."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "clean.ts", (
        "const x: string = 'hello';\n"
        "const y: number = 42;\n"
        "function greet(name: string): string {\n"
        "  return `Hello, ${name}!`;\n"
        "}\n"
    ))
    entries, total = detect_smells(tmp_path)
    assert entries == []
    assert total == 1


def test_returns_file_count(tmp_path):
    """detect_smells returns the total number of files checked."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "a.ts", "const a = 1;\n")
    _write(tmp_path, "b.tsx", "const b = 2;\n")
    _, total = detect_smells(tmp_path)
    assert total == 2


def test_entries_sorted_by_severity_then_count(tmp_path):
    """Entries should be sorted by severity (high first) then by descending count."""
    from desloppify.lang.typescript.detectors.smells import detect_smells

    _write(tmp_path, "bad.ts", (
        "try { foo(); } catch (e) { }\n"  # empty_catch (high)
        "const x: any = 1;\n"              # any_type (medium)
        "const y: any = 2;\n"              # any_type (medium) second hit
    ))
    entries, _ = detect_smells(tmp_path)
    if len(entries) >= 2:
        severity_order = {"high": 0, "medium": 1, "low": 2}
        for i in range(len(entries) - 1):
            cur_sev = severity_order.get(entries[i]["severity"], 9)
            next_sev = severity_order.get(entries[i + 1]["severity"], 9)
            if cur_sev == next_sev:
                assert entries[i]["count"] >= entries[i + 1]["count"]
            else:
                assert cur_sev <= next_sev
