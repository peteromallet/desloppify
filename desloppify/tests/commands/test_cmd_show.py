"""Tests for show command helper modules (formatting, payload, cmd flow)."""

from types import SimpleNamespace

import desloppify.app.commands.show.cmd as show_cmd_mod
import desloppify.app.commands.show.scope as show_scope_mod
import desloppify.state as state_mod
from desloppify.app.commands.helpers.runtime import CommandRuntime
from desloppify.app.commands.show.cmd import cmd_show
from desloppify.app.commands.show.scope import resolve_entity
from desloppify.app.commands.show.formatting import (
    DETAIL_DISPLAY,
    format_detail,
    suppressed_match_estimate,
)
from desloppify.app.commands.show.payload import ShowPayloadMeta, build_show_payload
from desloppify.app.commands.show.render import show_subjective_followup

# ---------------------------------------------------------------------------
# format_detail
# ---------------------------------------------------------------------------


class TestFormatDetail:
    """format_detail builds display-ready parts from a finding detail dict."""

    def test_empty_detail(self):
        assert format_detail({}) == []

    def test_simple_string_fields(self):
        parts = format_detail({"category": "imports", "kind": "default"})
        assert "category: imports" in parts
        assert "kind: default" in parts

    def test_line_number(self):
        parts = format_detail({"line": 42})
        assert "line: 42" in parts

    def test_lines_list_truncated(self):
        parts = format_detail({"lines": [1, 2, 3, 4, 5, 6, 7]})
        # Only first 5 should appear
        lines_part = [p for p in parts if p.startswith("lines:")]
        assert len(lines_part) == 1
        assert "6" not in lines_part[0]
        assert "1" in lines_part[0]

    def test_signals_list(self):
        parts = format_detail({"signals": ["a", "b", "c", "d"]})
        sig_part = [p for p in parts if p.startswith("signals:")][0]
        # Only first 3
        assert "a" in sig_part
        assert "c" in sig_part
        assert "d" not in sig_part

    def test_importers_zero_is_shown(self):
        """importers=0 is meaningful and should be displayed."""
        parts = format_detail({"importers": 0})
        assert "importers: 0" in parts

    def test_importers_none_is_hidden(self):
        """importers=None should not show up."""
        parts = format_detail({"importers": None})
        importers_parts = [p for p in parts if "importers" in p]
        assert importers_parts == []

    def test_count_zero_is_hidden(self):
        """count=0 is not meaningful and should be skipped."""
        parts = format_detail({"count": 0})
        count_parts = [p for p in parts if "count" in p]
        assert count_parts == []

    def test_review_truncated_at_80(self):
        long_review = "x" * 200
        parts = format_detail({"review": long_review})
        review_part = [p for p in parts if p.startswith("review:")][0]
        # Formatter truncates to 80 chars
        assert len(review_part) < 100  # "review: " prefix + 80 chars

    def test_dupe_pair_display(self):
        detail = {
            "fn_a": {"name": "foo", "line": 10},
            "fn_b": {"name": "bar", "line": 20},
        }
        parts = format_detail(detail)
        pair_part = [p for p in parts if "foo" in p and "bar" in p]
        assert len(pair_part) == 1
        assert "10" in pair_part[0]
        assert "20" in pair_part[0]

    def test_dupe_pair_missing_line(self):
        detail = {
            "fn_a": {"name": "foo"},
            "fn_b": {"name": "bar"},
        }
        parts = format_detail(detail)
        pair_part = [p for p in parts if "foo" in p and "bar" in p]
        assert len(pair_part) == 1

    def test_patterns_used_formatter(self):
        parts = format_detail({"patterns_used": ["singleton", "factory"]})
        pat_part = [p for p in parts if p.startswith("patterns:")][0]
        assert "singleton" in pat_part
        assert "factory" in pat_part

    def test_pattern_evidence_formatter(self):
        parts = format_detail({
            "pattern_evidence": {
                "useAutoSaveSettings": [{"file": "src/a.ts", "line": 12}],
                "useToolSettings": [{"file": "src/b.ts", "line": 9}, {"file": "src/c.ts", "line": 30}],
            }
        })
        ev_part = [p for p in parts if p.startswith("evidence:")][0]
        assert "useAutoSaveSettings:1 file(s)" in ev_part
        assert "useToolSettings:2 file(s)" in ev_part

    def test_outliers_truncated(self):
        parts = format_detail({"outliers": ["a", "b", "c", "d", "e", "f", "g"]})
        out_part = [p for p in parts if p.startswith("outliers:")][0]
        assert "f" not in out_part  # Only first 5


# ---------------------------------------------------------------------------
# build_show_payload
# ---------------------------------------------------------------------------


class TestBuildShowPayload:
    """build_show_payload produces structured JSON for query and --output."""

    def _make_finding(
        self, fid, *, file="a.ts", detector="unused", tier=2, confidence="high"
    ):
        return {
            "id": fid,
            "file": file,
            "detector": detector,
            "tier": tier,
            "confidence": confidence,
            "summary": f"Finding {fid}",
            "detail": {},
        }

    def test_empty_matches(self):
        result = build_show_payload([], "*.ts", "open")
        assert result["total"] == 0
        assert result["query"] == "*.ts"
        assert result["status_filter"] == "open"
        assert result["summary"]["files"] == 0
        assert result["by_file"] == {}


class TestSuppressedMatchEstimate:
    def _make_finding(self, fid, *, file="a.ts", detector="unused",
                      tier=2, confidence="high"):
        return {
            "id": fid, "file": file, "detector": detector,
            "tier": tier, "confidence": confidence,
            "summary": f"Finding {fid}", "detail": {},
        }

    def test_detector_name(self):
        assert suppressed_match_estimate("smells", {"smells": 4}) == 4

    def test_detector_prefix_pattern(self):
        assert suppressed_match_estimate("smells::*::x", {"smells": 7}) == 7

    def test_unknown_pattern_returns_zero(self):
        assert suppressed_match_estimate("nope", {"smells": 3}) == 0

    def test_single_finding(self):
        findings = [self._make_finding("unused::a.ts::foo")]
        result = build_show_payload(findings, "a.ts", "open")
        assert result["total"] == 1
        assert result["summary"]["files"] == 1
        assert result["summary"]["by_tier"] == {"T2": 1}
        assert result["summary"]["by_detector"] == {"unused": 1}
        assert "a.ts" in result["by_file"]
        assert len(result["by_file"]["a.ts"]) == 1

    def test_multiple_files_and_detectors(self):
        findings = [
            self._make_finding(
                "unused::a.ts::foo", file="a.ts", detector="unused", tier=2
            ),
            self._make_finding(
                "smells::b.ts::bar", file="b.ts", detector="smells", tier=3
            ),
            self._make_finding(
                "unused::a.ts::baz", file="a.ts", detector="unused", tier=2
            ),
        ]
        result = build_show_payload(findings, "*", "open")
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
        result = build_show_payload(findings, "*", "open")
        files = list(result["by_file"].keys())
        # a.ts has 3 findings, b.ts has 1 -- a.ts should come first
        assert files[0] == "a.ts"

    def test_by_detector_sorted_by_count_descending(self):
        findings = [
            self._make_finding("a1", detector="alpha"),
            self._make_finding("a2", detector="alpha"),
            self._make_finding("b1", detector="beta"),
        ]
        result = build_show_payload(findings, "*", "open")
        dets = list(result["summary"]["by_detector"].keys())
        assert dets[0] == "alpha"

    def test_payload_includes_hidden_metadata_when_provided(self):
        findings = [self._make_finding("a1", detector="alpha")]
        result = build_show_payload(
            findings,
            "*",
            "open",
            meta=ShowPayloadMeta(
                total_matches=4,
                hidden_by_detector={"alpha": 3},
                noise_budget=1,
                global_noise_budget=2,
            ),
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
        assert isinstance(DETAIL_DISPLAY, list)
        for entry in DETAIL_DISPLAY:
            assert len(entry) == 3
            key, label, fmt = entry
            assert isinstance(key, str)
            assert isinstance(label, str)
            assert fmt is None or callable(fmt)

    def test_cmd_show_exists(self):
        assert callable(cmd_show)


class TestShowSubjectiveFollowup:
    def test_penalty_state_prints_warning_and_next_step(self, capsys):
        state = {
            "subjective_integrity": {
                "status": "penalized",
                "target_score": 95.0,
                "matched_count": 2,
                "matched_dimensions": ["naming_quality", "logic_clarity"],
                "reset_dimensions": ["naming_quality", "logic_clarity"],
            },
            "dimension_scores": {
                "Naming quality": {
                    "score": 0.0,
                    "strict": 0.0,
                    "issues": 0,
                    "detectors": {"subjective_assessment": {}},
                },
                "Logic clarity": {
                    "score": 0.0,
                    "strict": 0.0,
                    "issues": 0,
                    "detectors": {"subjective_assessment": {}},
                },
            },
        }

        show_subjective_followup(state, 95.0)
        out = capsys.readouterr().out
        assert "were reset to 0.0 this scan" in out
        assert "Anti-gaming safeguard applied" in out
        assert (
            "review --run-batches --runner codex --parallel --scan-after-import --force-review-rerun --dimensions"
            in out
        )


class TestCmdShowBackendIntegration:
    def _patch_common(self, monkeypatch, *, state):
        monkeypatch.setattr(
            show_cmd_mod,
            "command_runtime",
            lambda _args: CommandRuntime(
                config={},
                state=state,
                state_path="/tmp/fake-state.json",
            ),
        )
        monkeypatch.setattr(
            state_mod, "resolve_finding_noise_settings", lambda _cfg: (10, 0, None)
        )
        monkeypatch.setattr(
            state_mod, "apply_finding_noise_budget", lambda matches, **_k: (matches, {})
        )
        monkeypatch.setattr(show_cmd_mod, "check_tool_staleness", lambda _state: None)
        monkeypatch.setattr(show_cmd_mod, "compute_narrative", lambda *a, **k: {})
        monkeypatch.setattr(show_cmd_mod, "resolve_lang", lambda _args: None)

    def test_show_uses_shared_queue_for_pattern_filter(self, monkeypatch, capsys):
        self._patch_common(
            monkeypatch,
            state={"last_scan": "2026-01-01", "findings": {}, "scan_path": "src"},
        )
        calls = []
        monkeypatch.setattr(show_cmd_mod, "write_query", lambda _payload: None)

        def fake_queue(_state, **kwargs):
            calls.append(kwargs)
            return {
                "items": [
                    {
                        "id": "smells::src/a.py::x",
                        "kind": "finding",
                        "detector": "smells",
                        "file": "src/a.py",
                        "tier": 3,
                        "confidence": "medium",
                        "summary": "X",
                        "detail": {},
                        "status": "open",
                    }
                ]
            }

        monkeypatch.setattr(show_scope_mod, "build_work_queue", fake_queue)
        args = SimpleNamespace(
            pattern="src/a.py",
            status="open",
            chronic=False,
            code=False,
            top=20,
            output=None,
            lang=None,
            path=".",
        )
        cmd_show(args)
        out = capsys.readouterr().out
        assert calls
        queue_options = calls[0]["options"]
        assert queue_options.scope == "src/a.py"
        assert queue_options.status == "open"
        assert "1 open findings matching 'src/a.py'" in out

    def test_show_chronic_forces_open_status(self, monkeypatch):
        self._patch_common(
            monkeypatch,
            state={"last_scan": "2026-01-01", "findings": {}, "scan_path": "."},
        )
        monkeypatch.setattr(show_cmd_mod, "write_query", lambda _payload: None)
        captured = {}

        def fake_queue(_state, **kwargs):
            captured.update(kwargs)
            return {"items": []}

        monkeypatch.setattr(show_scope_mod, "build_work_queue", fake_queue)
        args = SimpleNamespace(
            pattern=None,
            status="all",
            chronic=True,
            code=False,
            top=20,
            output=None,
            lang=None,
            path=".",
        )
        cmd_show(args)
        queue_options = captured["options"]
        assert queue_options.chronic is True
        assert queue_options.status == "open"

    def test_show_subjective_renders_dashboard(self, monkeypatch, capsys):
        self._patch_common(
            monkeypatch,
            state={
                "last_scan": "2026-01-01",
                "findings": {},
                "scan_path": ".",
                "dimension_scores": {
                    "Naming quality": {
                        "score": 88.0,
                        "strict": 85.0,
                        "issues": 2,
                        "detectors": {"subjective_assessment": {}},
                    },
                },
            },
        )
        monkeypatch.setattr(show_cmd_mod, "write_query", lambda _payload: None)

        args = SimpleNamespace(
            pattern="subjective",
            status="open",
            chronic=False,
            code=False,
            top=20,
            output=None,
            lang=None,
            path=".",
            notes=None,
        )
        cmd_show(args)
        out = capsys.readouterr().out
        assert "Subjective quality" in out
        assert "Naming quality" in out

    def test_show_subjective_dimension_by_key(self, monkeypatch, capsys):
        """show naming_quality → shows score + subjective explanation, not 'No findings'."""
        self._patch_common(
            monkeypatch,
            state={
                "last_scan": "2026-01-01",
                "findings": {
                    "review::src/a.py::1": {
                        "id": "review::src/a.py::1",
                        "detector": "review",
                        "status": "open",
                        "file": "src/a.py",
                        "detail": {"dimension": "naming_quality"},
                    },
                },
                "scan_path": ".",
                "dimension_scores": {
                    "Naming quality": {
                        "score": 90.0,
                        "strict": 88.0,
                        "issues": 1,
                        "detectors": {"subjective_assessment": {}},
                    },
                },
            },
        )
        monkeypatch.setattr(show_cmd_mod, "write_query", lambda _payload: None)
        monkeypatch.setattr(show_cmd_mod, "check_skill_version", lambda: None)

        def fake_queue(_state, **kwargs):
            return {"items": []}

        monkeypatch.setattr(show_scope_mod, "build_work_queue", fake_queue)
        args = SimpleNamespace(
            pattern="naming_quality",
            status="open",
            chronic=False,
            code=False,
            top=20,
            output=None,
            lang=None,
            path=".",
        )
        cmd_show(args)
        out = capsys.readouterr().out
        assert "Naming quality" in out
        assert "90.0%" in out
        assert "subjective dimension" in out
        assert "No open findings matching" not in out

    def test_show_mechanical_dimension_not_labeled_subjective(
        self, monkeypatch, capsys
    ):
        """show security with no open findings prints score + 'No open findings',
        NOT 'subjective dimension'."""
        self._patch_common(
            monkeypatch,
            state={
                "last_scan": "2026-01-01",
                "findings": {},
                "scan_path": ".",
                "dimension_scores": {
                    "Security": {
                        "score": 100.0,
                        "strict": 100.0,
                        "issues": 0,
                        "detectors": {"security": {}, "cycles": {}},
                    },
                },
            },
        )
        monkeypatch.setattr(show_cmd_mod, "write_query", lambda _payload: None)
        monkeypatch.setattr(show_cmd_mod, "check_skill_version", lambda: None)

        def fake_queue(_state, **kwargs):
            return {"items": []}

        monkeypatch.setattr(show_scope_mod, "build_work_queue", fake_queue)
        args = SimpleNamespace(
            pattern="security",
            status="open",
            chronic=False,
            code=False,
            top=20,
            output=None,
            lang=None,
            path=".",
        )
        cmd_show(args)
        out = capsys.readouterr().out
        assert "Security: 100.0% health" in out
        assert "No open findings for Security" in out
        assert "subjective dimension" not in out

    def test_show_mechanical_dimension_with_findings(self, monkeypatch, capsys):
        """show security with open findings from security AND cycles detectors shows both."""
        security_finding = {
            "id": "security::src/a.py::xss",
            "kind": "finding",
            "detector": "security",
            "file": "src/a.py",
            "tier": 4,
            "confidence": "high",
            "summary": "XSS vulnerability",
            "detail": {},
            "status": "open",
        }
        cycles_finding = {
            "id": "cycles::src/b.py::cycle",
            "kind": "finding",
            "detector": "cycles",
            "file": "src/b.py",
            "tier": 4,
            "confidence": "medium",
            "summary": "Dependency cycle",
            "detail": {},
            "status": "open",
        }
        self._patch_common(
            monkeypatch,
            state={
                "last_scan": "2026-01-01",
                "findings": {
                    "security::src/a.py::xss": security_finding,
                    "cycles::src/b.py::cycle": cycles_finding,
                },
                "scan_path": ".",
            },
        )
        monkeypatch.setattr(show_cmd_mod, "write_query", lambda _payload: None)
        monkeypatch.setattr(show_cmd_mod, "check_skill_version", lambda: None)

        call_count = {"n": 0}

        def fake_queue(_state, **kwargs):
            call_count["n"] += 1
            scope = kwargs.get("options", kwargs).scope
            if scope == "security":
                return {"items": [security_finding]}
            if scope == "cycles":
                return {"items": [cycles_finding]}
            return {"items": []}

        monkeypatch.setattr(show_scope_mod, "build_work_queue", fake_queue)
        args = SimpleNamespace(
            pattern="security",
            status="open",
            chronic=False,
            code=False,
            top=20,
            output=None,
            lang=None,
            path=".",
        )
        cmd_show(args)
        out = capsys.readouterr().out
        # Should render findings from both detectors
        assert "2 open findings matching 'Security'" in out
        assert "subjective dimension" not in out


class TestResolveEntity:
    """Unit tests for resolve_entity()."""

    def test_security_is_mechanical_dimension(self):
        entity = resolve_entity("security", {})
        assert entity.kind == "dimension"
        assert entity.is_subjective is False
        assert "security" in entity.detectors
        assert "cycles" in entity.detectors

    def test_naming_quality_is_subjective_dimension(self):
        state = {
            "dimension_scores": {
                "Naming quality": {
                    "score": 90.0,
                    "strict": 88.0,
                    "detectors": {"subjective_assessment": {}},
                },
            },
        }
        entity = resolve_entity("naming_quality", state)
        assert entity.kind == "dimension"
        assert entity.is_subjective is True
        assert entity.display_name == "Naming quality"

    def test_file_path_is_passthrough(self):
        entity = resolve_entity("src/foo.py", {})
        assert entity.kind == "file_or_pattern"
        assert entity.display_name == "src/foo.py"
        assert entity.is_subjective is False

    def test_subjective_is_special_view(self):
        entity = resolve_entity("subjective", {})
        assert entity.kind == "special_view"

    def test_concerns_is_special_view(self):
        entity = resolve_entity("concerns", {})
        assert entity.kind == "special_view"

    def test_file_health_is_mechanical_dimension(self):
        entity = resolve_entity("file_health", {})
        assert entity.kind == "dimension"
        assert entity.is_subjective is False
        assert "structural" in entity.detectors

    def test_duplication_is_mechanical_dimension(self):
        entity = resolve_entity("duplication", {})
        assert entity.kind == "dimension"
        assert entity.is_subjective is False
        assert "dupes" in entity.detectors
