"""Tests for desloppify.commands.show — helper/formatting functions."""

import pytest

from desloppify.commands.show import _format_detail, _build_show_payload, _DETAIL_DISPLAY


# ---------------------------------------------------------------------------
# _format_detail
# ---------------------------------------------------------------------------

class TestFormatDetail:
    """_format_detail builds display-ready parts from a finding detail dict."""

    def test_empty_detail(self):
        assert _format_detail({}) == []

    def test_simple_string_fields(self):
        parts = _format_detail({"category": "imports", "kind": "default"})
        assert "category: imports" in parts
        assert "kind: default" in parts

    def test_line_number(self):
        parts = _format_detail({"line": 42})
        assert "line: 42" in parts

    def test_lines_list_truncated(self):
        parts = _format_detail({"lines": [1, 2, 3, 4, 5, 6, 7]})
        # Only first 5 should appear
        lines_part = [p for p in parts if p.startswith("lines:")]
        assert len(lines_part) == 1
        assert "6" not in lines_part[0]
        assert "1" in lines_part[0]

    def test_signals_list(self):
        parts = _format_detail({"signals": ["a", "b", "c", "d"]})
        sig_part = [p for p in parts if p.startswith("signals:")][0]
        # Only first 3
        assert "a" in sig_part
        assert "c" in sig_part
        assert "d" not in sig_part

    def test_importers_zero_is_shown(self):
        """importers=0 is meaningful and should be displayed."""
        parts = _format_detail({"importers": 0})
        assert "importers: 0" in parts

    def test_importers_none_is_hidden(self):
        """importers=None should not show up."""
        parts = _format_detail({"importers": None})
        importers_parts = [p for p in parts if "importers" in p]
        assert importers_parts == []

    def test_count_zero_is_hidden(self):
        """count=0 is not meaningful and should be skipped."""
        parts = _format_detail({"count": 0})
        count_parts = [p for p in parts if "count" in p]
        assert count_parts == []

    def test_review_truncated_at_80(self):
        long_review = "x" * 200
        parts = _format_detail({"review": long_review})
        review_part = [p for p in parts if p.startswith("review:")][0]
        # Formatter truncates to 80 chars
        assert len(review_part) < 100  # "review: " prefix + 80 chars

    def test_dupe_pair_display(self):
        detail = {
            "fn_a": {"name": "foo", "line": 10},
            "fn_b": {"name": "bar", "line": 20},
        }
        parts = _format_detail(detail)
        pair_part = [p for p in parts if "foo" in p and "bar" in p]
        assert len(pair_part) == 1
        assert "10" in pair_part[0]
        assert "20" in pair_part[0]

    def test_dupe_pair_missing_line(self):
        detail = {
            "fn_a": {"name": "foo"},
            "fn_b": {"name": "bar"},
        }
        parts = _format_detail(detail)
        pair_part = [p for p in parts if "foo" in p and "bar" in p]
        assert len(pair_part) == 1

    def test_patterns_used_formatter(self):
        parts = _format_detail({"patterns_used": ["singleton", "factory"]})
        pat_part = [p for p in parts if p.startswith("patterns:")][0]
        assert "singleton" in pat_part
        assert "factory" in pat_part

    def test_outliers_truncated(self):
        parts = _format_detail({"outliers": ["a", "b", "c", "d", "e", "f", "g"]})
        out_part = [p for p in parts if p.startswith("outliers:")][0]
        assert "f" not in out_part  # Only first 5


# ---------------------------------------------------------------------------
# _build_show_payload
# ---------------------------------------------------------------------------

class TestBuildShowPayload:
    """_build_show_payload produces structured JSON for query and --output."""

    def _make_finding(self, fid, *, file="a.ts", detector="unused",
                      tier=2, confidence="high"):
        return {
            "id": fid, "file": file, "detector": detector,
            "tier": tier, "confidence": confidence,
            "summary": f"Finding {fid}", "detail": {},
        }

    def test_empty_matches(self):
        result = _build_show_payload([], "*.ts", "open")
        assert result["total"] == 0
        assert result["query"] == "*.ts"
        assert result["status_filter"] == "open"
        assert result["summary"]["files"] == 0
        assert result["by_file"] == {}

    def test_single_finding(self):
        findings = [self._make_finding("unused::a.ts::foo")]
        result = _build_show_payload(findings, "a.ts", "open")
        assert result["total"] == 1
        assert result["summary"]["files"] == 1
        assert result["summary"]["by_tier"] == {"T2": 1}
        assert result["summary"]["by_detector"] == {"unused": 1}
        assert "a.ts" in result["by_file"]
        assert len(result["by_file"]["a.ts"]) == 1

    def test_multiple_files_and_detectors(self):
        findings = [
            self._make_finding("unused::a.ts::foo", file="a.ts", detector="unused", tier=2),
            self._make_finding("smells::b.ts::bar", file="b.ts", detector="smells", tier=3),
            self._make_finding("unused::a.ts::baz", file="a.ts", detector="unused", tier=2),
        ]
        result = _build_show_payload(findings, "*", "open")
        assert result["total"] == 3
        assert result["summary"]["files"] == 2
        assert result["summary"]["by_tier"] == {"T2": 2, "T3": 1}
        assert result["summary"]["by_detector"]["unused"] == 2
        assert result["summary"]["by_detector"]["smells"] == 1

    def test_by_file_sorted_by_count_descending(self):
        findings = [
            self._make_finding("a1", file="a.ts"),
            self._make_finding("a2", file="a.ts"),
            self._make_finding("a3", file="a.ts"),
            self._make_finding("b1", file="b.ts"),
        ]
        result = _build_show_payload(findings, "*", "open")
        files = list(result["by_file"].keys())
        # a.ts has 3 findings, b.ts has 1 -- a.ts should come first
        assert files[0] == "a.ts"

    def test_by_detector_sorted_by_count_descending(self):
        findings = [
            self._make_finding("a1", detector="alpha"),
            self._make_finding("a2", detector="alpha"),
            self._make_finding("b1", detector="beta"),
        ]
        result = _build_show_payload(findings, "*", "open")
        dets = list(result["summary"]["by_detector"].keys())
        assert dets[0] == "alpha"

    def test_payload_includes_hidden_metadata_when_provided(self):
        findings = [self._make_finding("a1", detector="alpha")]
        result = _build_show_payload(
            findings,
            "*",
            "open",
            total_matches=4,
            hidden_by_detector={"alpha": 3},
            noise_budget=1,
            global_noise_budget=2,
        )
        assert result["total"] == 1
        assert result["total_matching"] == 4
        assert result["hidden"]["total"] == 3
        assert result["hidden"]["by_detector"] == {"alpha": 3}
        assert result["noise_budget"] == 1
        assert result["noise_global_budget"] == 2


# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------

class TestShowModuleSanity:
    """Verify the module imports and has expected exports."""

    def test_detail_display_is_list_of_tuples(self):
        assert isinstance(_DETAIL_DISPLAY, list)
        for entry in _DETAIL_DISPLAY:
            assert len(entry) == 3
            key, label, fmt = entry
            assert isinstance(key, str)
            assert isinstance(label, str)
            assert fmt is None or callable(fmt)

    def test_cmd_show_exists(self):
        from desloppify.commands.show import cmd_show
        assert callable(cmd_show)
