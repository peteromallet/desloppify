"""Tests for triage runner: stage prompts, validation, and orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

from desloppify.app.commands.plan.triage.validation.core import (
    _validate_reflect_issue_accounting,
)
from desloppify.app.commands.plan.triage.runner import codex_runner
from desloppify.app.commands.plan.triage.runner.stage_prompts import build_stage_prompt
from desloppify.app.commands.plan.triage.runner.stage_validation import (
    build_auto_attestation,
    validate_completion,
    validate_stage,
)
from desloppify.engine._plan.triage.prompt import TriageInput


def _make_triage_input(n_issues: int = 5) -> TriageInput:
    """Create a minimal TriageInput for testing."""
    issues = {}
    for i in range(n_issues):
        fid = f"review::src/foo{i}.ts::issue_{i}::abcd{i:04d}"
        issues[fid] = {
            "status": "open",
            "detector": "review",
            "file": f"src/foo{i}.ts",
            "summary": f"Issue {i} summary",
            "detail": {"dimension": f"dim_{i % 3}", "suggestion": "Fix it"},
        }
    return TriageInput(
        review_issues=issues,
        objective_backlog_issues={},
        existing_clusters={},
        dimension_scores={"dim_0": {"score": 70, "strict": 65, "failing": 2}},
        new_since_last=set(),
        resolved_since_last=set(),
        previously_dismissed=[],
        triage_version=1,
        resolved_issues={},
        completed_clusters=[],
    )


# ---------- Stage prompts ----------


def test_build_observe_prompt(tmp_path: Path) -> None:
    si = _make_triage_input()
    prompt = build_stage_prompt("observe", si, {}, repo_root=tmp_path)
    assert "OBSERVE" in prompt
    assert "desloppify plan triage --stage observe" in prompt
    assert "src/foo0.ts" in prompt  # issue data included


def test_build_reflect_prompt_includes_prior(tmp_path: Path) -> None:
    si = _make_triage_input()
    prior = {"observe": "My observation report about themes and root causes."}
    prompt = build_stage_prompt("reflect", si, prior, repo_root=tmp_path)
    assert "REFLECT" in prompt
    assert "My observation report" in prompt
    assert "## Required Issue Hashes" in prompt
    assert "## Coverage Ledger Template" in prompt
    assert "-> TODO" in prompt
    assert "exactly once" in prompt


def test_build_stage_prompt_places_prior_reports_before_issue_data(tmp_path: Path) -> None:
    si = _make_triage_input()
    prior = {"reflect": "Cluster blueprint goes here."}
    prompt = build_stage_prompt("organize", si, prior, repo_root=tmp_path)
    assert prompt.index("## Prior Stage Reports") < prompt.index("## Issue Summary")
    assert "Do not go\nsearch old triage runs" in prompt


def test_build_organize_prompt_uses_compact_issue_summary_and_relevant_prior_report(tmp_path: Path) -> None:
    si = _make_triage_input()
    prior = {
        "observe": "Long observe report",
        "reflect": "Cluster blueprint goes here.",
        "organize": "older organize report",
    }
    prompt = build_stage_prompt("organize", si, prior, repo_root=tmp_path)
    assert "### REFLECT Report" in prompt
    assert "### OBSERVE Report" not in prompt
    assert "## Issue Summary" in prompt
    assert "## Issue Data" not in prompt


def test_build_organize_prompt_carries_observe_file_evidence_forward(tmp_path: Path) -> None:
    si = _make_triage_input()
    prior = {"reflect": "Cluster blueprint goes here."}
    prompt = build_stage_prompt(
        "organize",
        si,
        prior,
        repo_root=tmp_path,
        stages_data={
            "observe": {
                "assessments": [
                    {
                        "hash": "abcd0000",
                        "verdict": "genuine",
                        "verdict_reasoning": "Shared files line up around the same module seam.",
                        "files_read": ["src/foo0.ts", "src/shared.ts"],
                        "recommendation": "Cluster these around the shared module edit.",
                    }
                ]
            }
        },
    )
    assert "### OBSERVE-EVIDENCE Report" in prompt
    assert "files_read: src/foo0.ts, src/shared.ts" in prompt
    assert "Shared files line up around the same module seam." in prompt


def test_build_reflect_prompt_output_only_for_codex_runner(tmp_path: Path) -> None:
    si = _make_triage_input()
    prior = {"observe": "My observation report about themes and root causes."}
    prompt = build_stage_prompt(
        "reflect",
        si,
        prior,
        repo_root=tmp_path,
        mode="output_only",
    )
    assert "Do NOT run any `desloppify` commands." in prompt
    assert "Do NOT debug, repair, reinstall, or inspect the `desloppify` CLI/environment." in prompt
    assert "orchestrator records and confirms the stage" in prompt
    assert "## Coverage Ledger Template" in prompt
    assert "CLI Command Reference" not in prompt
    assert 'desloppify plan triage --stage reflect --report "' not in prompt


def test_validate_reflect_issue_accounting_prefers_coverage_ledger() -> None:
    valid_ids = {
        "review::src/a.ts::alpha::aaaabbbb",
        "review::src/b.ts::beta::ccccdddd",
    }
    report = """
## Coverage Ledger
- aaaabbbb -> cluster "alpha"
- ccccdddd -> skip "false-positive"

## Cluster Blueprint
Cluster "alpha" handles aaaabbbb after the shared seam is stable.
"""
    ok, cited, missing, duplicates = _validate_reflect_issue_accounting(
        report=report,
        valid_ids=valid_ids,
    )
    assert ok
    assert cited == valid_ids
    assert missing == []
    assert duplicates == []


def test_validate_reflect_issue_accounting_accepts_named_short_ids() -> None:
    valid_ids = {
        "review::src/a.py::error_consistency::plugin_failures_look_like_absent_capabilities",
        "review::src/b.py::error_consistency::policy_load_masks_corruption",
    }
    report = """
## Coverage Ledger
- plugin_failures_look_like_absent_capabilities -> cluster "plugin-load-error-semantics"
- policy_load_masks_corruption -> skip "defer-to-followup"

## Cluster Blueprint
Cluster "plugin-load-error-semantics" owns loader error semantics.
"""
    ok, cited, missing, duplicates = _validate_reflect_issue_accounting(
        report=report,
        valid_ids=valid_ids,
    )
    assert ok
    assert cited == valid_ids
    assert missing == []
    assert duplicates == []


def test_validate_reflect_issue_accounting_handles_short_id_collisions() -> None:
    valid_ids = {
        "review::src/a.py::cross_module_architecture::review_packet_ownership_split",
        "review::src/b.py::high_level_elegance::review_packet_ownership_split",
    }
    report = """
## Coverage Ledger
- review_packet_ownership_split -> cluster "review-packet-lifecycle-ownership"
- review_packet_ownership_split -> cluster "review-packet-lifecycle-ownership"

## Cluster Blueprint
Cluster "review-packet-lifecycle-ownership" owns packet lifecycle policy.
"""
    ok, cited, missing, duplicates = _validate_reflect_issue_accounting(
        report=report,
        valid_ids=valid_ids,
    )
    assert ok
    assert cited == valid_ids
    assert missing == []
    assert duplicates == []


def test_build_organize_prompt(tmp_path: Path) -> None:
    si = _make_triage_input()
    prior = {"observe": "obs", "reflect": "ref"}
    prompt = build_stage_prompt("organize", si, prior, repo_root=tmp_path)
    assert "ORGANIZE" in prompt
    assert "desloppify plan cluster create" in prompt
    assert "--depends-on" in prompt
    assert "--effort" in prompt


def test_build_organize_prompt_uses_exact_cli_command_when_provided(tmp_path: Path) -> None:
    si = _make_triage_input()
    prior = {"observe": "obs", "reflect": "ref"}
    prompt = build_stage_prompt(
        "organize",
        si,
        prior,
        repo_root=tmp_path,
        cli_command="/tmp/run_desloppify.sh",
    )
    assert "/tmp/run_desloppify.sh plan cluster create" in prompt
    assert "Use the exact CLI command prefix shown" in prompt
    assert "Do NOT debug, repair, reinstall, or inspect the CLI/environment." in prompt
    assert "write a short plain-text summary to stdout" in prompt


def test_build_enrich_prompt(tmp_path: Path) -> None:
    si = _make_triage_input()
    prior = {"observe": "obs", "reflect": "ref", "organize": "org"}
    prompt = build_stage_prompt("enrich", si, prior, repo_root=tmp_path)
    assert "ENRICH" in prompt
    assert "--issue-refs" in prompt
    assert "exist on disk" in prompt


def test_build_organize_prompt_output_only_omits_mutating_cli_instructions(tmp_path: Path) -> None:
    si = _make_triage_input()
    prior = {"observe": "obs", "reflect": "ref"}
    prompt = build_stage_prompt(
        "organize",
        si,
        prior,
        repo_root=tmp_path,
        mode="output_only",
    )
    assert "write a plain-text organize report" in prompt
    assert "desloppify plan cluster create" not in prompt
    assert "desloppify plan skip --permanent" not in prompt


# ---------- Stage validation ----------


def _plan_with_stages(**kwargs: dict) -> dict:
    """Create a plan with triage stages."""
    stages = dict(kwargs)
    if stages and "strategize" not in stages:
        stages["strategize"] = {
            "report": "{}",
            "timestamp": "2026-03-10T00:00:00Z",
            "confirmed_at": "2026-03-10T00:00:00Z",
            "confirmed_text": "auto-confirmed",
        }
    return {
        "epic_triage_meta": {
            "triage_stages": stages,
        },
        "clusters": {},
        "queue_order": [],
    }


def test_validate_observe_missing(tmp_path: Path) -> None:
    plan = _plan_with_stages()
    ok, msg = validate_stage("observe", plan, {}, tmp_path)
    assert not ok
    assert "not recorded" in msg


def test_validate_observe_short_report(tmp_path: Path) -> None:
    plan = _plan_with_stages(observe={"report": "too short"})
    ok, msg = validate_stage("observe", plan, {}, tmp_path)
    assert not ok
    assert "too short" in msg


def test_validate_observe_ok(tmp_path: Path) -> None:
    # Report needs verdict entries when triage_input has hex IDs; use non-hex IDs to skip evidence parsing
    plan = _plan_with_stages(observe={"report": "x" * 150, "cited_ids": ["a", "b", "c", "d", "e"], "issue_count": 10})
    ok, msg = validate_stage("observe", plan, {}, tmp_path)
    assert ok, msg


def test_validate_observe_low_citations(tmp_path: Path) -> None:
    """Observe with too few issue citations should fail."""
    plan = _plan_with_stages(observe={"report": "x" * 150, "cited_ids": ["a"], "issue_count": 50})
    ok, msg = validate_stage("observe", plan, {}, tmp_path)
    assert not ok
    assert "cites only" in msg


def test_validate_reflect_requires_full_issue_accounting(tmp_path: Path) -> None:
    plan = _plan_with_stages(
        reflect={
            "report": "x" * 150,
            "cited_ids": ["review::design::aaaabbbb"],
            "issue_count": 2,
            "missing_issue_ids": ["review::design::ccccdddd"],
            "duplicate_issue_ids": [],
        }
    )
    ok, msg = validate_stage("reflect", plan, {}, tmp_path)
    assert not ok
    assert "unaccounted" in msg


def test_validate_organize_no_clusters(tmp_path: Path) -> None:
    plan = _plan_with_stages(organize={"report": "x" * 150})
    state = {"issues": {"review::a::b": {"status": "open", "detector": "review"}}}
    ok, msg = validate_stage("organize", plan, state, tmp_path)
    assert not ok
    assert "No manual clusters" in msg


def test_validate_enrich_bad_paths(tmp_path: Path) -> None:
    plan = _plan_with_stages(enrich={"report": "x" * 150})
    plan["clusters"] = {
        "test-cluster": {
            "issue_ids": ["review::a::b"],
            "description": "test",
            "action_steps": [
                {"title": "fix", "detail": "Update src/nonexistent.ts and fix the imports. " + "x" * 40, "effort": "small", "issue_refs": ["review::a::b"]}
            ],
        }
    }
    ok, msg = validate_stage("enrich", plan, {}, tmp_path)
    assert not ok
    assert "file path" in msg


def test_validate_enrich_missing_effort(tmp_path: Path) -> None:
    """Enrich should block on missing effort tags."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.ts").write_text("export {}")
    plan = _plan_with_stages(enrich={"report": "x" * 150})
    plan["clusters"] = {
        "test-cluster": {
            "issue_ids": ["review::a::b"],
            "description": "test",
            "action_steps": [
                {"title": "fix", "detail": "Update src/foo.ts to remove dead code and fix the pattern. " + "x" * 30, "issue_refs": ["review::a::b"]}
            ],
        }
    }
    ok, msg = validate_stage("enrich", plan, {}, tmp_path)
    assert not ok
    assert "effort" in msg


def test_validate_enrich_missing_issue_refs(tmp_path: Path) -> None:
    """Enrich should block on missing issue_refs."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.ts").write_text("export {}")
    plan = _plan_with_stages(enrich={"report": "x" * 150})
    plan["clusters"] = {
        "test-cluster": {
            "issue_ids": ["review::a::b"],
            "description": "test",
            "action_steps": [
                {"title": "fix", "detail": "Update src/foo.ts to remove dead code and fix the pattern. " + "x" * 30, "effort": "small"}
            ],
        }
    }
    ok, msg = validate_stage("enrich", plan, {}, tmp_path)
    assert not ok
    assert "issue_refs" in msg


def test_validate_enrich_vague_detail(tmp_path: Path) -> None:
    """Enrich should block on steps with vague detail (short, no paths)."""
    plan = _plan_with_stages(enrich={"report": "x" * 150})
    plan["clusters"] = {
        "test-cluster": {
            "issue_ids": ["review::a::b"],
            "description": "test",
            "action_steps": [
                {"title": "fix", "detail": "Fix the thing", "effort": "small", "issue_refs": ["review::a::b"]}
            ],
        }
    }
    ok, msg = validate_stage("enrich", plan, {}, tmp_path)
    assert not ok
    assert "vague" in msg


def test_validate_enrich_ignores_out_of_scope_clusters_for_frozen_triage(tmp_path: Path) -> None:
    """Runner enrich validation should only inspect clusters tied to the active triage session."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "current.ts").write_text("export {}")
    plan = _plan_with_stages(enrich={"report": "x" * 150})
    plan["epic_triage_meta"]["active_triage_issue_ids"] = ["review::current::issue"]
    plan["clusters"] = {
        "current": {
            "issue_ids": ["review::current::issue"],
            "description": "current batch",
            "action_steps": [
                {
                    "title": "fix current",
                    "detail": "Update src/current.ts to simplify the active path and remove duplication. " + "x" * 30,
                    "effort": "small",
                    "issue_refs": ["review::current::issue"],
                }
            ],
        },
        "legacy": {
            "issue_ids": ["review::legacy::issue"],
            "description": "old batch",
            "action_steps": [
                {
                    "title": "old vague step",
                    "detail": "",
                    "effort": "small",
                }
            ],
        },
    }
    state = {
        "issues": {
            "review::current::issue": {"status": "open", "detector": "review"},
            "review::legacy::issue": {"status": "open", "detector": "review"},
        }
    }
    ok, msg = validate_stage("enrich", plan, state, tmp_path)
    assert ok, msg


def test_validate_sense_check_ignores_out_of_scope_clusters_for_frozen_triage(tmp_path: Path) -> None:
    """Decision-ledger coverage should only include live targets from the active triage session."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "current.ts").write_text("export {}")
    plan = _plan_with_stages(
        **{
            "sense-check": {
                "report": "\n".join(
                    [
                        "Verified src/current.ts lines 1-10: the active cluster is concrete, safe, and removes duplication without adding indirection. " + "x" * 20,
                        "## Decision Ledger",
                        "- current -> keep",
                    ]
                )
            }
        }
    )
    plan["epic_triage_meta"]["active_triage_issue_ids"] = ["review::current::issue"]
    plan["clusters"] = {
        "current": {
            "issue_ids": ["review::current::issue"],
            "description": "current batch",
            "action_steps": [
                {
                    "title": "fix current",
                    "detail": "Update src/current.ts to simplify the active path and remove duplication. " + "x" * 30,
                    "effort": "small",
                    "issue_refs": ["review::current::issue"],
                }
            ],
        },
        "legacy": {
            "issue_ids": ["review::legacy::issue"],
            "description": "old batch",
            "action_steps": [
                {
                    "title": "old valid step",
                    "detail": "Update src/legacy.ts to simplify the old path and remove duplication. " + "x" * 30,
                    "effort": "small",
                    "issue_refs": ["review::legacy::issue"],
                }
            ],
        },
    }
    state = {
        "issues": {
            "review::current::issue": {"status": "open", "detector": "review"},
            "review::legacy::issue": {"status": "open", "detector": "review"},
        }
    }
    ok, msg = validate_stage("sense-check", plan, state, tmp_path)
    assert ok, msg


# ---------- Underspecified steps (AND→OR fix) ----------


def test_underspecified_catches_refs_but_no_detail(tmp_path: Path) -> None:
    """A step with issue_refs but no detail should be caught."""
    from desloppify.app.commands.plan.triage.validation.core import (
        _underspecified_steps,
    )

    plan = {
        "clusters": {
            "c1": {
                "issue_ids": ["review::a::b"],
                "action_steps": [
                    {"title": "shell step", "issue_refs": ["review::a::b"], "effort": "small"}
                ],
            }
        }
    }
    results = _underspecified_steps(plan)
    assert len(results) == 1
    assert results[0][0] == "c1"
    assert results[0][1] == 1  # 1 bare step


def test_underspecified_catches_detail_but_no_refs(tmp_path: Path) -> None:
    """A step with detail but no issue_refs should be caught."""
    from desloppify.app.commands.plan.triage.validation.core import (
        _underspecified_steps,
    )

    plan = {
        "clusters": {
            "c1": {
                "issue_ids": ["review::a::b"],
                "action_steps": [
                    {"title": "orphan step", "detail": "Update src/foo.ts lines 10-20", "effort": "small"}
                ],
            }
        }
    }
    results = _underspecified_steps(plan)
    assert len(results) == 1


def test_underspecified_passes_complete_step() -> None:
    """A step with both detail and issue_refs should pass."""
    from desloppify.app.commands.plan.triage.validation.core import (
        _underspecified_steps,
    )

    plan = {
        "clusters": {
            "c1": {
                "issue_ids": ["review::a::b"],
                "action_steps": [
                    {
                        "title": "good step",
                        "detail": "Update src/foo.ts to fix the issue",
                        "issue_refs": ["review::a::b"],
                        "effort": "small",
                    }
                ],
            }
        }
    }
    results = _underspecified_steps(plan)
    assert results == []


# ---------- Vague detail flags missing detail ----------


def test_vague_detail_flags_missing_detail(tmp_path: Path) -> None:
    """A step with no detail at all should be flagged as vague."""
    from desloppify.app.commands.plan.triage.validation.core import (
        _steps_with_vague_detail,
    )

    plan = {
        "clusters": {
            "c1": {
                "issue_ids": ["review::a::b"],
                "action_steps": [
                    {"title": "empty step", "issue_refs": ["review::a::b"], "effort": "small"}
                ],
            }
        }
    }
    results = _steps_with_vague_detail(plan, tmp_path)
    assert len(results) == 1
    assert results[0][0] == "c1"
    assert results[0][2] == "empty step"


def test_vague_detail_flags_empty_string_detail(tmp_path: Path) -> None:
    """A step with empty string detail should be flagged as vague."""
    from desloppify.app.commands.plan.triage.validation.core import (
        _steps_with_vague_detail,
    )

    plan = {
        "clusters": {
            "c1": {
                "issue_ids": ["review::a::b"],
                "action_steps": [
                    {"title": "blank step", "detail": "", "issue_refs": ["review::a::b"], "effort": "small"}
                ],
            }
        }
    }
    results = _steps_with_vague_detail(plan, tmp_path)
    assert len(results) == 1


# ---------- Auto attestation ----------


def test_auto_attestation_observe() -> None:
    si = _make_triage_input()
    plan = {}
    att = build_auto_attestation("observe", plan, si)
    assert len(att) >= 80
    assert "dim_" in att


def test_auto_attestation_organize() -> None:
    si = _make_triage_input()
    plan = {
        "clusters": {
            "fix-naming": {"issue_ids": ["review::a::b"]},
        }
    }
    att = build_auto_attestation("organize", plan, si)
    assert len(att) >= 80
    assert "fix-naming" in att


def test_auto_attestation_organize_zero_issue_batch() -> None:
    si = _make_triage_input(0)
    att = build_auto_attestation("organize", {"clusters": {}}, si)
    assert len(att) >= 80
    assert "zero open review issues" in att.lower()


# ---------- Completion validation ----------


def test_validate_completion_missing_stages(tmp_path: Path) -> None:
    plan = _plan_with_stages(observe={"report": "x" * 150, "confirmed_at": "2024-01-01"})
    ok, msg = validate_completion(plan, {}, tmp_path)
    assert not ok
    assert "reflect" in msg


def test_validate_completion_self_dependency(tmp_path: Path) -> None:
    plan = _plan_with_stages(
        observe={"report": "x" * 150, "confirmed_at": "t"},
        reflect={"report": "x" * 150, "confirmed_at": "t"},
        organize={"report": "x" * 150, "confirmed_at": "t"},
        enrich={"report": "x" * 150, "confirmed_at": "t"},
        **{"sense-check": {"report": "x" * 150, "confirmed_at": "t"}},
        **{"value-check": {"report": "x" * 150, "confirmed_at": "t"}},
    )
    plan["clusters"] = {
        "self-dep": {
            "issue_ids": ["review::a::b"],
            "description": "test",
            "action_steps": [{"title": "fix", "detail": "d", "issue_refs": ["review::a::b"]}],
            "depends_on_clusters": ["self-dep"],
        }
    }
    ok, msg = validate_completion(plan, {"issues": {"review::a::b": {"status": "open", "detector": "review"}}}, tmp_path)
    assert not ok
    assert "depends on itself" in msg


def test_validate_completion_surfaces_all_trivial_cluster_advisory(tmp_path: Path) -> None:
    plan = _plan_with_stages(
        observe={"report": "x" * 150, "confirmed_at": "t"},
        reflect={"report": "x" * 150, "confirmed_at": "t"},
        organize={"report": "x" * 150, "confirmed_at": "t"},
        enrich={"report": "x" * 150, "confirmed_at": "t"},
        **{"sense-check": {"report": "x" * 150, "confirmed_at": "t"}},
        **{"value-check": {"report": "x" * 150, "confirmed_at": "t"}},
    )
    plan["clusters"] = {
        "all-trivial": {
            "issue_ids": ["review::a::b"],
            "description": "test",
            "action_steps": [
                {
                    "title": "rename constant",
                    "detail": "Apply rename in src/foo.ts for consistency.",
                    "issue_refs": ["review::a::b"],
                    "effort": "trivial",
                }
            ],
        }
    }
    ok, msg = validate_completion(
        plan,
        {"issues": {"review::a::b": {"status": "open", "detector": "review"}}},
        tmp_path,
    )
    assert ok
    assert msg.startswith("Advisory:")
    assert "all-trivial" in msg


def test_validate_completion_allows_zero_issue_noop(tmp_path: Path) -> None:
    plan = _plan_with_stages(
        observe={"report": "x" * 150, "confirmed_at": "t"},
        reflect={"report": "x" * 150, "confirmed_at": "t"},
        organize={"report": "x" * 150, "confirmed_at": "t"},
        enrich={"report": "x" * 150, "confirmed_at": "t"},
        **{"sense-check": {"report": "x" * 150, "confirmed_at": "t"}},
        **{"value-check": {"report": "x" * 150, "confirmed_at": "t"}},
    )
    ok, msg = validate_completion(plan, {"issues": {}}, tmp_path)
    assert ok
    assert msg == ""


def test_validate_completion_ignores_out_of_scope_clusters_for_frozen_triage(tmp_path: Path) -> None:
    """Completion should only validate clusters tied to the frozen triage issue set."""
    plan = _plan_with_stages(
        observe={"report": "x" * 150, "confirmed_at": "t"},
        reflect={"report": "x" * 150, "confirmed_at": "t"},
        organize={"report": "x" * 150, "confirmed_at": "t"},
        enrich={"report": "x" * 150, "confirmed_at": "t"},
        **{"sense-check": {"report": "x" * 150, "confirmed_at": "t"}},
        **{"value-check": {"report": "x" * 150, "confirmed_at": "t"}},
    )
    plan["epic_triage_meta"]["active_triage_issue_ids"] = ["review::current::issue"]
    plan["clusters"] = {
        "current": {
            "issue_ids": ["review::current::issue"],
            "description": "current batch",
            "action_steps": [
                {
                    "title": "fix current",
                    "detail": "Update src/current.ts to simplify the active path and remove duplication. " + "x" * 30,
                    "effort": "small",
                    "issue_refs": ["review::current::issue"],
                }
            ],
        },
        "legacy-self-dep": {
            "issue_ids": ["review::legacy::issue"],
            "description": "old batch",
            "action_steps": [
                {
                    "title": "old step",
                    "detail": "",
                    "effort": "small",
                }
            ],
            "depends_on_clusters": ["legacy-self-dep"],
        },
    }
    state = {
        "issues": {
            "review::current::issue": {"status": "open", "detector": "review"},
            "review::legacy::issue": {"status": "open", "detector": "review"},
        }
    }
    ok, msg = validate_completion(plan, state, tmp_path)
    assert ok, msg


def test_validate_stage_organize_allows_zero_issue_noop(tmp_path: Path) -> None:
    plan = _plan_with_stages(organize={"report": "x" * 150})
    ok, msg = validate_stage("organize", plan, {"issues": {}}, tmp_path, triage_input=_make_triage_input(0))
    assert ok
    assert msg == ""


def test_validate_stage_sense_check_allows_zero_issue_noop(tmp_path: Path) -> None:
    plan = _plan_with_stages(**{"sense-check": {"report": "x" * 150}})
    ok, msg = validate_stage("sense-check", plan, {"issues": {}}, tmp_path, triage_input=_make_triage_input(0))
    assert ok
    assert msg == ""


# ---------- Sense-check prompts ----------


def test_sense_check_prompt_includes_cluster_data(tmp_path: Path) -> None:
    """Content prompt should include cluster steps, issue refs, and repo root."""
    from desloppify.app.commands.plan.triage.runner.stage_prompts import (
        build_sense_check_content_prompt,
    )

    plan = {
        "clusters": {
            "fix-hooks": {
                "issue_ids": ["review::src/foo.ts::hook_issue::abcd1234"],
                "description": "Fix hook issues",
                "action_steps": [
                    {
                        "title": "Extract hook",
                        "detail": "In src/hooks/useX.ts lines 10-50, extract filter logic.",
                        "effort": "medium",
                        "issue_refs": ["review::src/foo.ts::hook_issue::abcd1234"],
                    }
                ],
            }
        }
    }
    prompt = build_sense_check_content_prompt(
        cluster_name="fix-hooks", plan=plan, repo_root=tmp_path,
    )
    assert "fix-hooks" in prompt
    assert "1 steps" in prompt
    assert "Extract hook" in prompt
    assert "medium" in prompt
    assert "abcd1234" in prompt
    assert str(tmp_path) in prompt
    assert "LINE NUMBERS" in prompt
    assert "STALENESS" in prompt
    assert "ONLY reference file paths that already exist on disk" in prompt
    assert "do NOT invent a future filename" in prompt


def test_sense_check_structure_prompt_includes_clusters(tmp_path: Path) -> None:
    """Structure prompt should list all manual clusters and their dependencies."""
    from desloppify.app.commands.plan.triage.runner.stage_prompts import (
        build_sense_check_structure_prompt,
    )

    plan = {
        "clusters": {
            "cluster-a": {
                "issue_ids": ["review::a::b"],
                "description": "First cluster",
                "action_steps": [{"title": "Step A1", "detail": "Fix src/a.ts"}],
            },
            "cluster-b": {
                "issue_ids": ["review::c::d"],
                "description": "Second cluster",
                "action_steps": [{"title": "Step B1", "detail": "Fix src/b.ts"}],
                "depends_on_clusters": ["cluster-a"],
            },
        }
    }
    prompt = build_sense_check_structure_prompt(plan=plan, repo_root=tmp_path)
    assert "cluster-a" in prompt
    assert "cluster-b" in prompt
    assert "depends_on: cluster-a" in prompt
    assert "SHARED FILES" in prompt
    assert "CIRCULAR DEPS" in prompt
    assert "Do NOT add cascade steps that point at speculative future files" in prompt


# ---------- Sense-check validation ----------


def test_sense_check_validation_reruns_enrich_checks(tmp_path: Path) -> None:
    """Sense-check validation should fail on bad paths just like enrich."""
    plan = _plan_with_stages(**{"sense-check": {"report": "x" * 150}})
    plan["clusters"] = {
        "test-cluster": {
            "issue_ids": ["review::a::b"],
            "description": "test",
            "action_steps": [
                {
                    "title": "fix",
                    "detail": "Update src/nonexistent.ts and fix the imports. " + "x" * 40,
                    "effort": "small",
                    "issue_refs": ["review::a::b"],
                }
            ],
        }
    }
    ok, msg = validate_stage("sense-check", plan, {}, tmp_path)
    assert not ok
    assert "file path" in msg or "don't exist" in msg


def test_sense_check_validation_ok(tmp_path: Path) -> None:
    """Sense-check passes when report is long enough and all enrich checks pass."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.ts").write_text("export {}")
    plan = _plan_with_stages(
        **{
            "sense-check": {
                "report": (
                    "## Decision Ledger\n"
                    "- test-cluster -> keep\n\n"
                    "Verified test-cluster steps: src/foo.ts lines 10-20 match description. "
                    "Effort tags accurate. " + "x" * 60
                )
            }
        }
    )
    plan["clusters"] = {
        "test-cluster": {
            "issue_ids": ["review::a::b"],
            "description": "test",
            "action_steps": [
                {
                    "title": "fix",
                    "detail": "Update src/foo.ts to remove dead code and fix the pattern. " + "x" * 30,
                    "effort": "small",
                    "issue_refs": ["review::a::b"],
                }
            ],
        }
    }
    ok, msg = validate_stage("sense-check", plan, {}, tmp_path)
    assert ok


def test_sense_check_validation_uses_frozen_value_targets(tmp_path: Path) -> None:
    """Validation should accept decision-ledger targets captured before value-pass pruning."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.ts").write_text("export {}")
    plan = _plan_with_stages(
        **{
            "sense-check": {
                "report": (
                    "## Decision Ledger\n"
                    "- kept-cluster -> keep\n"
                    "- pruned-cluster -> skip\n"
                    "- review::.::holistic::cross_module_architecture::private_framework_boundary_still_leaks -> skip\n\n"
                    "Verified kept-cluster in src/foo.ts lines 1-10 and recorded why the pruned targets were removed during the value pass. "
                    + "x" * 80
                ),
                "value_targets": [
                    "kept-cluster",
                    "pruned-cluster",
                    "review::.::holistic::cross_module_architecture::private_framework_boundary_still_leaks",
                ],
            }
        }
    )
    plan["clusters"] = {
        "kept-cluster": {
            "issue_ids": ["review::a::b"],
            "description": "active",
            "action_steps": [
                {
                    "title": "fix",
                    "detail": "Update src/foo.ts to simplify the active path and remove duplication. " + "x" * 40,
                    "effort": "small",
                    "issue_refs": ["review::a::b"],
                }
            ],
        }
    }
    ok, msg = validate_stage("sense-check", plan, {}, tmp_path)
    assert ok, msg


def test_sense_check_stage_in_pipeline_order() -> None:
    """sense-check must appear between enrich and commit in TRIAGE_STAGE_IDS."""
    from desloppify.engine._plan.constants import TRIAGE_STAGE_IDS

    ids = list(TRIAGE_STAGE_IDS)
    assert "triage::sense-check" in ids
    enrich_idx = ids.index("triage::enrich")
    sense_idx = ids.index("triage::sense-check")
    commit_idx = ids.index("triage::commit")
    assert enrich_idx < sense_idx < commit_idx


# ---------- Plan lock ----------


def test_plan_lock_prevents_concurrent_writes(tmp_path: Path) -> None:
    """plan_lock should serialize access via file locking."""
    import threading

    from desloppify.engine._plan.persistence import plan_lock

    plan_file = tmp_path / "plan.json"
    plan_file.write_text("{}")

    results: list[int] = []
    barrier = threading.Barrier(2)

    def worker(value: int) -> None:
        barrier.wait()  # ensure both threads start ~simultaneously
        with plan_lock(plan_file):
            # If locking works, only one thread is in here at a time
            current = len(results)
            results.append(value)
            assert len(results) == current + 1  # no interleaving

    t1 = threading.Thread(target=worker, args=(1,))
    t2 = threading.Thread(target=worker, args=(2,))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert sorted(results) == [1, 2]


# ---------- Triage codex runner ----------


def test_run_triage_stage_defaults_to_text_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Triage runner should validate plain text output by default (not JSON-only)."""
    captured: dict[str, object] = {}

    def _fake_run_codex_batch(*, prompt, repo_root, output_file, log_file, deps, codex_batch_command_fn=None):
        captured["prompt"] = prompt
        captured["repo_root"] = repo_root
        captured["output_file"] = output_file
        captured["log_file"] = log_file
        captured["validator"] = deps.validate_output_fn
        return 0

    monkeypatch.setattr(codex_runner, "run_codex_batch", _fake_run_codex_batch)

    output_file = tmp_path / "triage.raw.txt"
    log_file = tmp_path / "triage.log"
    ret = codex_runner.run_triage_stage(
        prompt="triage prompt",
        repo_root=tmp_path,
        output_file=output_file,
        log_file=log_file,
    )
    assert ret.ok
    assert ret.exit_code == 0
    assert ret.reason is None
    assert captured["validator"] is codex_runner._output_file_has_text


def test_run_triage_stage_allows_validator_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit validate_output_fn should override default text validator."""
    captured: dict[str, object] = {}

    def _fake_run_codex_batch(*, prompt, repo_root, output_file, log_file, deps, codex_batch_command_fn=None):
        captured["validator"] = deps.validate_output_fn
        return 0

    monkeypatch.setattr(codex_runner, "run_codex_batch", _fake_run_codex_batch)

    def _custom_validator(_path: Path) -> bool:
        return True

    ret = codex_runner.run_triage_stage(
        prompt="triage prompt",
        repo_root=tmp_path,
        output_file=tmp_path / "triage.raw.txt",
        log_file=tmp_path / "triage.log",
        validate_output_fn=_custom_validator,
    )
    assert ret.ok
    assert ret.exit_code == 0
    assert ret.reason is None
    assert captured["validator"] is _custom_validator
