"""Tests for desloppify.lang.typescript.detectors.logs — tagged console.log detection."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _set_project_root(tmp_path, monkeypatch):
    """Point PROJECT_ROOT at the tmp directory."""
    monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))
    import desloppify.utils as utils_mod
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# ── detect_logs ──────────────────────────────────────────────


class TestDetectLogs:
    def test_detects_tagged_console_log(self, tmp_path):
        """Finds console.log with [Tag] prefix."""
        from desloppify.lang.typescript.detectors.logs import detect_logs

        _write(tmp_path, "debug.ts", "console.log('[Debug] something happened');\n")
        entries, total = detect_logs(tmp_path)
        assert len(entries) == 1
        assert entries[0]["tag"] == "Debug"
        assert total == 1

    def test_detects_console_warn_tagged(self, tmp_path):
        """Finds console.warn with [Tag] prefix."""
        from desloppify.lang.typescript.detectors.logs import detect_logs

        _write(tmp_path, "warn.ts", "console.warn('[Warning] something');\n")
        entries, _ = detect_logs(tmp_path)
        assert len(entries) == 1
        assert entries[0]["tag"] == "Warning"

    def test_detects_console_info_tagged(self, tmp_path):
        """Finds console.info with [Tag] prefix."""
        from desloppify.lang.typescript.detectors.logs import detect_logs

        _write(tmp_path, "info.ts", "console.info('[Perf] timing data');\n")
        entries, _ = detect_logs(tmp_path)
        assert len(entries) == 1

    def test_detects_console_debug_tagged(self, tmp_path):
        """Finds console.debug with [Tag] prefix."""
        from desloppify.lang.typescript.detectors.logs import detect_logs

        _write(tmp_path, "dbg.ts", "console.debug('[Trace] step 1');\n")
        entries, _ = detect_logs(tmp_path)
        assert len(entries) == 1

    def test_no_tag_not_detected(self, tmp_path):
        """console.log without a [Tag] is not detected."""
        from desloppify.lang.typescript.detectors.logs import detect_logs

        _write(tmp_path, "clean.ts", "console.log('normal message');\n")
        entries, _ = detect_logs(tmp_path)
        assert len(entries) == 0

    def test_multiple_tags_in_one_file(self, tmp_path):
        """Multiple tagged logs in the same file are all detected."""
        from desloppify.lang.typescript.detectors.logs import detect_logs

        _write(tmp_path, "multi.ts", (
            "console.log('[Auth] login attempt');\n"
            "console.log('[Auth] login success');\n"
            "console.log('[Perf] render time');\n"
        ))
        entries, _ = detect_logs(tmp_path)
        assert len(entries) == 3

    def test_deduplicates_same_line(self, tmp_path):
        """Same file+line is deduplicated (from pattern overlap)."""
        from desloppify.lang.typescript.detectors.logs import detect_logs

        # A line that could match both patterns should still produce only 1 entry
        _write(tmp_path, "one.ts", "console.log('[Tag] message');\n")
        entries, _ = detect_logs(tmp_path)
        assert len(entries) == 1

    def test_returns_file_count(self, tmp_path):
        """detect_logs returns total file count."""
        from desloppify.lang.typescript.detectors.logs import detect_logs

        _write(tmp_path, "a.ts", "const x = 1;\n")
        _write(tmp_path, "b.tsx", "const y = 2;\n")
        _, total = detect_logs(tmp_path)
        assert total == 2

    def test_empty_directory(self, tmp_path):
        """Empty directory returns no entries."""
        from desloppify.lang.typescript.detectors.logs import detect_logs

        entries, total = detect_logs(tmp_path)
        assert entries == []
        assert total == 0

    def test_emoji_prefixed_tag(self, tmp_path):
        """Detects tags with emoji prefix like console.log('emoji [Tag] ...')."""
        from desloppify.lang.typescript.detectors.logs import detect_logs

        # The pattern allows up to 4 characters before the [
        _write(tmp_path, "emoji.ts", "console.log('>> [Tag] message');\n")
        entries, _ = detect_logs(tmp_path)
        assert len(entries) == 1

    def test_tsx_files_included(self, tmp_path):
        """Both .ts and .tsx files are scanned."""
        from desloppify.lang.typescript.detectors.logs import detect_logs

        _write(tmp_path, "comp.tsx", "console.log('[Render] component');\n")
        entries, total = detect_logs(tmp_path)
        assert len(entries) == 1
        assert total >= 1


# ── TAG_EXTRACT_RE ───────────────────────────────────────────


class TestTagExtractRe:
    def test_extracts_tag(self):
        from desloppify.lang.typescript.detectors.logs import TAG_EXTRACT_RE

        m = TAG_EXTRACT_RE.search("[MyTag] some text")
        assert m is not None
        assert m.group(1) == "MyTag"

    def test_extracts_first_tag(self):
        from desloppify.lang.typescript.detectors.logs import TAG_EXTRACT_RE

        m = TAG_EXTRACT_RE.search("[First] and [Second]")
        assert m is not None
        assert m.group(1) == "First"

    def test_no_tag(self):
        from desloppify.lang.typescript.detectors.logs import TAG_EXTRACT_RE

        m = TAG_EXTRACT_RE.search("no tags here")
        assert m is None
