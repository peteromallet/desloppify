"""Tests for triage tooling fixes: path validation, effort tags, overlaps, dependencies."""

from __future__ import annotations

import argparse
from pathlib import Path

from desloppify.app.commands.plan.cluster import update as cluster_update_mod

from desloppify.app.commands.plan.triage.validation.core import (
    _cluster_file_overlaps,
    _steps_with_bad_paths,
    _steps_without_effort,
)


# ---------- Path validation ----------


def _plan_with_steps(steps: list[dict], cluster_name: str = "test-cluster") -> dict:
    return {
        "clusters": {
            cluster_name: {
                "issue_ids": ["review::a::b"],
                "action_steps": steps,
            }
        }
    }


def test_steps_with_bad_paths_valid(tmp_path: Path) -> None:
    """Step with a valid path should not be flagged."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.ts").write_text("export {}")
    plan = _plan_with_steps([{"title": "fix", "detail": "Update src/foo.ts to remove dead code"}])
    result = _steps_with_bad_paths(plan, tmp_path)
    assert result == []


def test_steps_with_bad_paths_invalid(tmp_path: Path) -> None:
    """Step with a non-existent path should be flagged."""
    (tmp_path / "src").mkdir()
    plan = _plan_with_steps([{"title": "fix", "detail": "Update src/nonexistent.ts to fix bug"}])
    result = _steps_with_bad_paths(plan, tmp_path)
    assert len(result) == 1
    cluster_name, step_num, bad = result[0]
    assert cluster_name == "test-cluster"
    assert step_num == 1
    assert "src/nonexistent.ts" in bad


def test_steps_with_bad_paths_extension_swap(tmp_path: Path) -> None:
    """Step referencing .ts that exists as .tsx should not be flagged."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.tsx").write_text("export {}")
    plan = _plan_with_steps([{"title": "fix", "detail": "Update src/foo.ts component"}])
    result = _steps_with_bad_paths(plan, tmp_path)
    assert result == []


def test_steps_with_bad_paths_no_paths(tmp_path: Path) -> None:
    """Step with no file paths in detail should not be flagged."""
    plan = _plan_with_steps([{"title": "fix", "detail": "Refactor the error handling logic"}])
    result = _steps_with_bad_paths(plan, tmp_path)
    assert result == []


def test_steps_with_bad_paths_monorepo_prefix(tmp_path: Path) -> None:
    """Monorepo paths like packages/backend/src/foo.ts should be validated correctly."""
    (tmp_path / "packages" / "backend" / "src").mkdir(parents=True)
    (tmp_path / "packages" / "backend" / "src" / "middleware" / "auth.ts").parent.mkdir(parents=True)
    (tmp_path / "packages" / "backend" / "src" / "middleware" / "auth.ts").write_text("export {}")
    plan = _plan_with_steps([
        {"title": "fix", "detail": "Update packages/backend/src/middleware/auth.ts to fix auth"},
    ])
    result = _steps_with_bad_paths(plan, tmp_path)
    assert result == [], f"Valid monorepo path was flagged as bad: {result}"


def test_steps_with_bad_paths_monorepo_invalid(tmp_path: Path) -> None:
    """Monorepo paths that don't exist should still be flagged."""
    (tmp_path / "packages" / "backend" / "src").mkdir(parents=True)
    plan = _plan_with_steps([
        {"title": "fix", "detail": "Update packages/backend/src/nonexistent.ts"},
    ])
    result = _steps_with_bad_paths(plan, tmp_path)
    assert len(result) == 1
    assert "packages/backend/src/nonexistent.ts" in result[0][2]


def test_steps_with_bad_paths_auto_cluster_skipped(tmp_path: Path) -> None:
    """Auto clusters should be skipped."""
    plan = {
        "clusters": {
            "auto-cluster": {
                "auto": True,
                "issue_ids": ["review::a::b"],
                "action_steps": [{"title": "fix", "detail": "Update src/bad.ts"}],
            }
        }
    }
    result = _steps_with_bad_paths(plan, tmp_path)
    assert result == []


# ---------- Effort tags ----------


def test_steps_without_effort_all_tagged() -> None:
    """Steps with effort tags should not be flagged."""
    plan = _plan_with_steps([
        {"title": "step 1", "effort": "small"},
        {"title": "step 2", "effort": "large"},
    ])
    result = _steps_without_effort(plan)
    assert result == []


def test_steps_without_effort_missing() -> None:
    """Steps without effort tags should be flagged."""
    plan = _plan_with_steps([
        {"title": "step 1", "effort": "small"},
        {"title": "step 2"},
        {"title": "step 3"},
    ])
    result = _steps_without_effort(plan)
    assert len(result) == 1
    name, missing, total = result[0]
    assert name == "test-cluster"
    assert missing == 2
    assert total == 3


def test_steps_without_effort_invalid_tag() -> None:
    """Invalid effort values should be flagged as missing."""
    plan = _plan_with_steps([{"title": "step 1", "effort": "huge"}])
    result = _steps_without_effort(plan)
    assert len(result) == 1


# ---------- Cross-cluster file overlap ----------


def test_cluster_file_overlaps_detected() -> None:
    """Two clusters referencing the same file should be reported."""
    plan = {
        "clusters": {
            "cluster-a": {
                "issue_ids": ["review::a::b"],
                "action_steps": [{"title": "fix", "detail": "Update src/shared.ts"}],
            },
            "cluster-b": {
                "issue_ids": ["review::c::d"],
                "action_steps": [{"title": "fix", "detail": "Refactor src/shared.ts"}],
            },
        }
    }
    result = _cluster_file_overlaps(plan)
    assert len(result) == 1
    a, b, files = result[0]
    assert "src/shared.ts" in files


def test_cluster_file_overlaps_none() -> None:
    """Clusters with no overlapping files should be clean."""
    plan = {
        "clusters": {
            "cluster-a": {
                "issue_ids": ["review::a::b"],
                "action_steps": [{"title": "fix", "detail": "Update src/foo.ts"}],
            },
            "cluster-b": {
                "issue_ids": ["review::c::d"],
                "action_steps": [{"title": "fix", "detail": "Refactor src/bar.ts"}],
            },
        }
    }
    result = _cluster_file_overlaps(plan)
    assert result == []


def test_cluster_file_overlaps_auto_excluded() -> None:
    """Auto clusters should be excluded from overlap detection."""
    plan = {
        "clusters": {
            "auto-a": {
                "auto": True,
                "issue_ids": ["review::a::b"],
                "action_steps": [{"title": "fix", "detail": "Update src/shared.ts"}],
            },
            "cluster-b": {
                "issue_ids": ["review::c::d"],
                "action_steps": [{"title": "fix", "detail": "Refactor src/shared.ts"}],
            },
        }
    }
    result = _cluster_file_overlaps(plan)
    assert result == []


# ---------- Dependency field ----------


def test_depends_on_persisted(monkeypatch, capsys, tmp_path: Path) -> None:
    """--depends-on should persist on cluster dict."""
    from desloppify.app.commands.plan.cluster import dispatch as cluster_handlers

    test_plan = {
        "clusters": {
            "cluster-a": {"issue_ids": ["review::a::b"], "action_steps": []},
            "cluster-b": {"issue_ids": ["review::c::d"], "action_steps": []},
        },
        "queue_order": [],
        "execution_log": [],
    }
    saved_plans: list[dict] = []
    monkeypatch.setattr(cluster_update_mod, "load_plan", lambda: test_plan)
    monkeypatch.setattr(cluster_update_mod, "save_plan", lambda p: saved_plans.append(p))
    monkeypatch.setattr(cluster_update_mod, "append_log_entry", lambda *a, **kw: None)

    args = argparse.Namespace(
        cluster_name="cluster-b",
        description=None, steps=None, steps_file=None,
        add_step=None, detail=None, update_step=None,
        remove_step=None, done_step=None, undone_step=None,
        priority=None, effort=None, depends_on=["cluster-a"],
        issue_refs=None, state=None,
    )
    cluster_handlers._cmd_cluster_update(args)
    assert test_plan["clusters"]["cluster-b"]["depends_on_clusters"] == ["cluster-a"]


def test_depends_on_repeated_updates_append(monkeypatch) -> None:
    """Repeated --depends-on updates should preserve existing dependencies."""
    from desloppify.app.commands.plan.cluster import dispatch as cluster_handlers

    test_plan = {
        "clusters": {
            "cluster-a": {"issue_ids": [], "action_steps": []},
            "cluster-b": {"issue_ids": [], "action_steps": []},
            "cluster-c": {"issue_ids": [], "action_steps": []},
        },
        "queue_order": [],
        "execution_log": [],
    }
    monkeypatch.setattr(cluster_update_mod, "load_plan", lambda: test_plan)
    monkeypatch.setattr(cluster_update_mod, "save_plan", lambda _plan: None)
    monkeypatch.setattr(cluster_update_mod, "append_log_entry", lambda *_args, **_kwargs: None)

    def update(*dependencies: str) -> None:
        args = argparse.Namespace(
            cluster_name="cluster-c",
            description=None,
            steps=None,
            steps_file=None,
            add_step=None,
            detail=None,
            update_step=None,
            remove_step=None,
            done_step=None,
            undone_step=None,
            priority=None,
            effort=None,
            depends_on=list(dependencies),
            issue_refs=None,
            state=None,
        )
        cluster_handlers._cmd_cluster_update(args)

    update("cluster-a")
    update("cluster-b")

    assert test_plan["clusters"]["cluster-c"]["depends_on_clusters"] == [
        "cluster-a",
        "cluster-b",
    ]


def test_depends_on_invalid_cluster(monkeypatch, capsys) -> None:
    """--depends-on with invalid cluster name should error."""
    from desloppify.app.commands.plan.cluster import dispatch as cluster_handlers

    test_plan = {
        "clusters": {
            "cluster-a": {"issue_ids": ["review::a::b"], "action_steps": []},
        },
        "queue_order": [],
        "execution_log": [],
    }
    monkeypatch.setattr(cluster_update_mod, "load_plan", lambda: test_plan)

    args = argparse.Namespace(
        cluster_name="cluster-a",
        description=None, steps=None, steps_file=None,
        add_step=None, detail=None, update_step=None,
        remove_step=None, done_step=None, undone_step=None,
        priority=None, effort=None, depends_on=["nonexistent"],
        issue_refs=None, state=None,
    )
    cluster_handlers._cmd_cluster_update(args)
    captured = capsys.readouterr()
    assert "nonexistent" in captured.out


# ---------- Effort on steps ----------


def test_effort_persisted_add_step(monkeypatch, capsys) -> None:
    """--effort should persist on new step."""
    from desloppify.app.commands.plan.cluster import dispatch as cluster_handlers

    test_plan = {
        "clusters": {
            "cluster-a": {"issue_ids": ["review::a::b"], "action_steps": []},
        },
        "queue_order": [],
        "execution_log": [],
    }
    monkeypatch.setattr(cluster_update_mod, "load_plan", lambda: test_plan)
    monkeypatch.setattr(cluster_update_mod, "save_plan", lambda p: None)
    monkeypatch.setattr(cluster_update_mod, "append_log_entry", lambda *a, **kw: None)

    args = argparse.Namespace(
        cluster_name="cluster-a",
        description=None, steps=None, steps_file=None,
        add_step="Fix the thing", detail="Details here",
        update_step=None, remove_step=None,
        done_step=None, undone_step=None,
        priority=None, effort="small", depends_on=None,
        issue_refs=None, state=None,
    )
    cluster_handlers._cmd_cluster_update(args)
    steps = test_plan["clusters"]["cluster-a"]["action_steps"]
    assert len(steps) == 1
    assert steps[0]["effort"] == "small"


def test_effort_persisted_update_step(monkeypatch, capsys) -> None:
    """--effort should persist on updated step."""
    from desloppify.app.commands.plan.cluster import dispatch as cluster_handlers

    test_plan = {
        "clusters": {
            "cluster-a": {
                "issue_ids": ["review::a::b"],
                "action_steps": [{"title": "old step"}],
            },
        },
        "queue_order": [],
        "execution_log": [],
    }
    monkeypatch.setattr(cluster_update_mod, "load_plan", lambda: test_plan)
    monkeypatch.setattr(cluster_update_mod, "save_plan", lambda p: None)
    monkeypatch.setattr(cluster_update_mod, "append_log_entry", lambda *a, **kw: None)

    args = argparse.Namespace(
        cluster_name="cluster-a",
        description=None, steps=None, steps_file=None,
        add_step=None, detail="New detail",
        update_step=1, remove_step=None,
        done_step=None, undone_step=None,
        priority=None, effort="medium", depends_on=None,
        issue_refs=None, state=None,
    )
    cluster_handlers._cmd_cluster_update(args)
    steps = test_plan["clusters"]["cluster-a"]["action_steps"]
    assert steps[0]["effort"] == "medium"
    assert steps[0]["detail"] == "New detail"


# ---------- Step title length cap ----------


def test_long_title_warning(monkeypatch, capsys) -> None:
    """Long step title should trigger warning."""
    from desloppify.app.commands.plan.cluster import dispatch as cluster_handlers

    test_plan = {
        "clusters": {
            "cluster-a": {"issue_ids": ["review::a::b"], "action_steps": []},
        },
        "queue_order": [],
        "execution_log": [],
    }
    monkeypatch.setattr(cluster_update_mod, "load_plan", lambda: test_plan)
    monkeypatch.setattr(cluster_update_mod, "save_plan", lambda p: None)
    monkeypatch.setattr(cluster_update_mod, "append_log_entry", lambda *a, **kw: None)

    long_title = "x" * 200
    args = argparse.Namespace(
        cluster_name="cluster-a",
        description=None, steps=None, steps_file=None,
        add_step=long_title, detail=None,
        update_step=None, remove_step=None,
        done_step=None, undone_step=None,
        priority=None, effort=None, depends_on=None,
        issue_refs=None, state=None,
    )
    cluster_handlers._cmd_cluster_update(args)
    captured = capsys.readouterr()
    assert "Warning" in captured.out
    assert "200 chars" in captured.out


def test_short_title_no_warning(monkeypatch, capsys) -> None:
    """Short step title should not trigger warning."""
    from desloppify.app.commands.plan.cluster import dispatch as cluster_handlers

    test_plan = {
        "clusters": {
            "cluster-a": {"issue_ids": ["review::a::b"], "action_steps": []},
        },
        "queue_order": [],
        "execution_log": [],
    }
    monkeypatch.setattr(cluster_update_mod, "load_plan", lambda: test_plan)
    monkeypatch.setattr(cluster_update_mod, "save_plan", lambda p: None)
    monkeypatch.setattr(cluster_update_mod, "append_log_entry", lambda *a, **kw: None)

    args = argparse.Namespace(
        cluster_name="cluster-a",
        description=None, steps=None, steps_file=None,
        add_step="Fix the thing", detail=None,
        update_step=None, remove_step=None,
        done_step=None, undone_step=None,
        priority=None, effort=None, depends_on=None,
        issue_refs=None, state=None,
    )
    cluster_handlers._cmd_cluster_update(args)
    captured = capsys.readouterr()
    assert "Warning" not in captured.out


# ---------- Issue refs on steps ----------


def test_issue_refs_persisted_add_step(monkeypatch, capsys) -> None:
    """--issue-refs should persist on new step."""
    from desloppify.app.commands.plan.cluster import dispatch as cluster_handlers

    test_plan = {
        "clusters": {
            "cluster-a": {"issue_ids": ["review::a::b"], "action_steps": []},
        },
        "queue_order": [],
        "execution_log": [],
    }
    monkeypatch.setattr(cluster_update_mod, "load_plan", lambda: test_plan)
    monkeypatch.setattr(cluster_update_mod, "save_plan", lambda p: None)
    monkeypatch.setattr(cluster_update_mod, "append_log_entry", lambda *a, **kw: None)

    args = argparse.Namespace(
        cluster_name="cluster-a",
        description=None, steps=None, steps_file=None,
        add_step="Fix the thing", detail="Details",
        update_step=None, remove_step=None,
        done_step=None, undone_step=None,
        priority=None, effort=None, depends_on=None,
        issue_refs=["review::a::b", "review::c::d"], state=None,
    )
    cluster_handlers._cmd_cluster_update(args)
    steps = test_plan["clusters"]["cluster-a"]["action_steps"]
    assert steps[0]["issue_refs"] == ["review::a::b", "review::c::d"]


# ---------- New validation functions ----------


def test_steps_missing_issue_refs() -> None:
    """Steps without issue_refs should be flagged."""
    from desloppify.app.commands.plan.triage.validation.core import _steps_missing_issue_refs

    plan = _plan_with_steps([
        {"title": "step 1", "detail": "fix things", "issue_refs": ["review::a::b"]},
        {"title": "step 2", "detail": "fix more things"},
    ])
    result = _steps_missing_issue_refs(plan)
    assert len(result) == 1
    name, missing, total = result[0]
    assert name == "test-cluster"
    assert missing == 1
    assert total == 2


def test_steps_missing_issue_refs_all_have_refs() -> None:
    """Steps with issue_refs should not be flagged."""
    from desloppify.app.commands.plan.triage.validation.core import _steps_missing_issue_refs

    plan = _plan_with_steps([
        {"title": "step 1", "detail": "fix things", "issue_refs": ["review::a::b"]},
    ])
    result = _steps_missing_issue_refs(plan)
    assert result == []


def test_steps_with_vague_detail_flagged(tmp_path: Path) -> None:
    """Short detail with no file paths should be flagged as vague."""
    from desloppify.app.commands.plan.triage.validation.core import _steps_with_vague_detail

    plan = _plan_with_steps([{"title": "fix", "detail": "Fix the error handling"}])
    result = _steps_with_vague_detail(plan, tmp_path)
    assert len(result) == 1
    name, step_num, title = result[0]
    assert name == "test-cluster"
    assert step_num == 1


def test_steps_with_vague_detail_ok_with_path(tmp_path: Path) -> None:
    """Short detail with a file path should not be flagged."""
    from desloppify.app.commands.plan.triage.validation.core import _steps_with_vague_detail

    plan = _plan_with_steps([{"title": "fix", "detail": "Fix src/foo.ts error"}])
    result = _steps_with_vague_detail(plan, tmp_path)
    assert result == []


def test_steps_with_vague_detail_ok_long(tmp_path: Path) -> None:
    """Long detail (80+ chars) without a path should not be flagged."""
    from desloppify.app.commands.plan.triage.validation.core import _steps_with_vague_detail

    plan = _plan_with_steps([{"title": "fix", "detail": "x" * 80}])
    result = _steps_with_vague_detail(plan, tmp_path)
    assert result == []


def test_steps_referencing_skipped_issues() -> None:
    """Steps with issue_refs pointing to wontfixed issues should be flagged."""
    from desloppify.app.commands.plan.triage.validation.core import _steps_referencing_skipped_issues

    plan = _plan_with_steps([
        {"title": "fix", "detail": "d", "issue_refs": ["review::a::b", "review::skipped::c"]},
    ])
    plan["wontfix"] = {"review::skipped::c": {"reason": "false positive"}}
    result = _steps_referencing_skipped_issues(plan)
    assert len(result) == 1
    name, step_num, stale = result[0]
    assert "review::skipped::c" in stale


def test_steps_referencing_skipped_issues_clean() -> None:
    """Steps with no skipped refs should not be flagged."""
    from desloppify.app.commands.plan.triage.validation.core import _steps_referencing_skipped_issues

    plan = _plan_with_steps([
        {"title": "fix", "detail": "d", "issue_refs": ["review::a::b"]},
    ])
    plan["wontfix"] = {}
    result = _steps_referencing_skipped_issues(plan)
    assert result == []


# ---------- Directory scatter detection ----------


def test_directory_scatter_detected() -> None:
    """Cluster with steps spanning 5+ directories should be flagged."""
    from desloppify.app.commands.plan.triage.validation.core import _clusters_with_directory_scatter

    plan = _plan_with_steps([
        {"title": "s1", "detail": "Fix src/domains/billing/hooks/useAutoTopup.ts"},
        {"title": "s2", "detail": "Fix src/domains/media-lightbox/hooks/useShare.ts"},
        {"title": "s3", "detail": "Fix src/shared/hooks/useTimestamp.ts"},
        {"title": "s4", "detail": "Fix src/tools/travel-between-images/components/Timeline.tsx"},
        {"title": "s5", "detail": "Fix src/tools/edit-images/hooks/useInline.ts"},
        {"title": "s6", "detail": "Fix src/features/tasks/components/TaskPane.tsx"},
    ])
    result = _clusters_with_directory_scatter(plan)
    assert len(result) == 1
    name, dir_count, _ = result[0]
    assert name == "test-cluster"
    assert dir_count >= 5


def test_directory_scatter_not_flagged_few_dirs() -> None:
    """Cluster with steps in few directories should not be flagged."""
    from desloppify.app.commands.plan.triage.validation.core import _clusters_with_directory_scatter

    plan = _plan_with_steps([
        {"title": "s1", "detail": "Fix src/domains/billing/hooks/useAutoTopup.ts"},
        {"title": "s2", "detail": "Fix src/domains/billing/components/Credits.tsx"},
        {"title": "s3", "detail": "Fix src/domains/billing/types.ts"},
    ])
    result = _clusters_with_directory_scatter(plan)
    assert result == []


# ---------- High step-to-issue ratio ----------


def test_high_step_ratio_detected() -> None:
    """Cluster with more steps than issues should be flagged."""
    from desloppify.app.commands.plan.triage.validation.core import _clusters_with_high_step_ratio

    plan = {
        "clusters": {
            "test-cluster": {
                "issue_ids": ["r1", "r2", "r3"],
                "action_steps": [
                    {"title": "s1"}, {"title": "s2"}, {"title": "s3"}, {"title": "s4"},
                ],
            }
        }
    }
    result = _clusters_with_high_step_ratio(plan)
    assert len(result) == 1
    name, steps, issues, ratio = result[0]
    assert name == "test-cluster"
    assert steps == 4
    assert issues == 3
    assert ratio > 1.0


def test_high_step_ratio_ok() -> None:
    """Cluster with fewer steps than issues should not be flagged."""
    from desloppify.app.commands.plan.triage.validation.core import _clusters_with_high_step_ratio

    plan = {
        "clusters": {
            "test-cluster": {
                "issue_ids": ["r1", "r2", "r3", "r4"],
                "action_steps": [
                    {"title": "s1"}, {"title": "s2"},
                ],
            }
        }
    }
    result = _clusters_with_high_step_ratio(plan)
    assert result == []


def test_high_step_ratio_skips_small_clusters() -> None:
    """Small clusters (< 3 issues) should not be checked."""
    from desloppify.app.commands.plan.triage.validation.core import _clusters_with_high_step_ratio

    plan = {
        "clusters": {
            "test-cluster": {
                "issue_ids": ["r1", "r2"],
                "action_steps": [
                    {"title": "s1"}, {"title": "s2"}, {"title": "s3"},
                ],
            }
        }
    }
    result = _clusters_with_high_step_ratio(plan)
    assert result == []


# ---------- Auto-start preserves stage data ----------


def test_auto_start_preserves_existing_stages(monkeypatch) -> None:
    """Auto-start in stage commands should NOT clear existing triage_stages."""
    import desloppify.app.commands.plan.triage.stages.observe as observe_flow

    existing_stages = {
        "observe": {"report": "analysis", "confirmed_at": "2026-01-01"},
        "reflect": {"report": "strategy", "confirmed_at": "2026-01-01"},
    }
    test_plan = {
        "queue_order": [],  # empty = has_triage_in_queue returns False
        "epic_triage_meta": {"triage_stages": dict(existing_stages)},
        "clusters": {},
        "execution_log": [],
    }

    saved_plans = []
    monkeypatch.setattr(
        observe_flow, "has_triage_in_queue", lambda p: False,
    )
    monkeypatch.setattr(
        observe_flow, "inject_triage_stages", lambda p: None,
    )

    class FakeRuntime:
        def __init__(self):
            self.state = {"issues": {}}

    class FakeServices:
        def command_runtime(self, args):
            return FakeRuntime()
        def load_plan(self):
            return test_plan
        def save_plan(self, p):
            saved_plans.append(dict(p))
        def collect_triage_input(self, plan, state):
            from types import SimpleNamespace
            return SimpleNamespace(open_issues={}, resolved_issues={})
        def extract_issue_citations(self, report, valid_ids):
            return set()
        def append_log_entry(self, plan, action, **kw):
            pass

    args = argparse.Namespace(report="x" * 200, stage="observe")
    observe_flow._cmd_stage_observe(args, services=FakeServices())

    # The key assertion: existing stages should be preserved
    meta = test_plan["epic_triage_meta"]
    assert "observe" in meta["triage_stages"]
    # The OLD confirmed observe should still be there (or overwritten by new observe,
    # but NOT wiped to empty dict)
    assert meta["triage_stages"] != {}


# ---------- Orphaned cluster detection ----------


def test_orphaned_cluster_detected() -> None:
    """Cluster with steps but no issues should be noted in advisory."""
    from desloppify.app.commands.plan.triage.runner.stage_validation import validate_stage

    plan = {
        "clusters": {
            "good-cluster": {
                "issue_ids": ["review::a::b"],
                "action_steps": [{"title": "step 1"}],
                "description": "desc",
            },
            "orphaned-cluster": {
                "issue_ids": [],
                "action_steps": [{"title": "orphaned step"}],
                "description": "desc",
            },
        },
        "epic_triage_meta": {
            "triage_stages": {
                "organize": {
                    "report": "Organized issues into good-cluster with proper structure and priorities explained thoroughly here.",
                },
                "reflect": {"timestamp": "2020-01-01T00:00:00Z"},
            },
        },
        "execution_log": [
            {"timestamp": "2020-01-02T00:00:00Z", "action": "cluster_create"},
            {"timestamp": "2020-01-02T00:00:01Z", "action": "cluster_add"},
            {"timestamp": "2020-01-02T00:00:02Z", "action": "cluster_update"},
        ],
    }
    state = {"issues": {"review::a::b": {"status": "open", "detector": "review"}}}
    ok, msg = validate_stage("organize", plan, state, Path("/tmp"))
    assert ok  # advisory, not blocking
    assert "orphaned-cluster" in msg.lower()


def test_no_orphaned_cluster_warning() -> None:
    """Clusters with issues should not trigger orphaned note."""
    from desloppify.app.commands.plan.triage.runner.stage_validation import validate_stage

    plan = {
        "clusters": {
            "good-cluster": {
                "issue_ids": ["review::a::b"],
                "action_steps": [{"title": "step 1"}],
                "description": "desc",
            },
        },
        "epic_triage_meta": {
            "triage_stages": {
                "organize": {
                    "report": "Organized issues into good-cluster with proper structure and priorities explained thoroughly here.",
                },
                "reflect": {"timestamp": "2020-01-01T00:00:00Z"},
            },
        },
        "execution_log": [
            {"timestamp": "2020-01-02T00:00:00Z", "action": "cluster_create"},
            {"timestamp": "2020-01-02T00:00:01Z", "action": "cluster_add"},
            {"timestamp": "2020-01-02T00:00:02Z", "action": "cluster_update"},
        ],
    }
    state = {"issues": {"review::a::b": {"status": "open", "detector": "review"}}}
    ok, msg = validate_stage("organize", plan, state, Path("/tmp"))
    assert ok
    assert "orphan" not in msg.lower()
