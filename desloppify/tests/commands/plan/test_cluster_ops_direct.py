"""Direct tests for plan cluster operation helper modules."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

import desloppify.app.commands.plan.cluster.dispatch as cluster_dispatch_mod
import desloppify.app.commands.plan.cluster.ops_display as cluster_display_mod
import desloppify.app.commands.plan.cluster.ops_manage as cluster_manage_mod
import desloppify.app.commands.plan.cluster.ops_reorder as cluster_reorder_mod
import desloppify.app.commands.plan.cluster.steps as cluster_steps_mod
import desloppify.app.commands.plan.cluster.update as cluster_update_mod
import desloppify.app.commands.plan.cluster.update_flow as cluster_update_flow_mod
from desloppify.base.exception_sets import CommandError


def test_cluster_steps_print_step_variants(capsys) -> None:
    cluster_steps_mod.print_step(
        1,
        {"title": "Structured", "detail": "line one\nline two", "issue_refs": ["x", "y"]},
        colorize_fn=lambda text, _tone: text,
    )
    cluster_steps_mod.print_step(
        2,
        {"title": "Done step", "done": True},
        colorize_fn=lambda text, _tone: text,
    )
    out = capsys.readouterr().out
    assert "1. [ ] Structured" in out
    assert "line one" in out
    assert "Refs: x, y" in out
    assert "2. [x] Done step" in out


def test_cluster_display_helpers_and_renderers(monkeypatch, capsys) -> None:
    plan = {
        "active_cluster": "alpha",
        "queue_order": ["i1", "i2"],
        "clusters": {
            "alpha": {
                "description": "Primary",
                "action": "desloppify plan resolve alpha",
                "priority": 1,
                "issue_ids": ["i1"],
                "action_steps": [{"title": "Do work", "issue_refs": ["i1"]}],
            },
            "beta": {"issue_ids": ["i2"], "description": "Secondary", "priority": 2, "auto": True},
        },
    }

    monkeypatch.setattr(cluster_display_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(
        cluster_display_mod,
        "command_runtime",
        lambda _args: SimpleNamespace(
            state={
                "issues": {
                    "i1": {
                        "file": "src/a.py",
                        "detail": {"lines": [3, 7]},
                        "summary": "Issue summary",
                    }
                }
            }
        ),
    )

    cluster_display_mod._cmd_cluster_show(argparse.Namespace(cluster_name="alpha"))
    out_show = capsys.readouterr().out
    assert "Cluster: alpha" in out_show
    assert "Members (1): i1" in out_show

    cluster_display_mod._cmd_cluster_list(
        argparse.Namespace(verbose=True, missing_steps=False)
    )
    out_list = capsys.readouterr().out
    assert "2 clusters" in out_list
    assert "alpha" in out_list
    assert "beta" in out_list

    sorted_clusters, pos_map = cluster_display_mod._sorted_clusters_by_queue_pos(
        plan["clusters"],
        plan["queue_order"],
    )
    assert [name for name, _ in sorted_clusters] == ["alpha", "beta"]
    assert pos_map["alpha"] == 0


def test_cluster_manage_create_export_import_merge(monkeypatch, tmp_path, capsys) -> None:
    plan = {"clusters": {}, "queue_order": []}

    def _create(plan_data, name, description, action=None):
        cluster = {
            "issue_ids": [],
            "description": description,
            "action": action,
        }
        plan_data.setdefault("clusters", {})[name] = cluster
        return cluster

    monkeypatch.setattr(cluster_manage_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(cluster_manage_mod, "create_cluster", _create)
    monkeypatch.setattr(cluster_manage_mod, "append_log_entry", lambda *_a, **_k: None)
    monkeypatch.setattr(cluster_manage_mod, "save_plan", lambda *_a, **_k: None)
    monkeypatch.setattr(cluster_manage_mod, "parse_steps_file", lambda _text: [{"title": "step"}])
    monkeypatch.setattr(
        cluster_manage_mod,
        "_import_yaml_module",
        lambda: SimpleNamespace(
            dump=lambda data, **_kwargs: (
                "clusters:\n"
                f"- name: {data['clusters'][0]['name']}\n"
            ),
            safe_load=lambda _text: {
                "clusters": [
                    {
                        "name": "new-cluster",
                        "description": "imported",
                        "steps": [{"title": "first"}],
                    }
                ]
            },
        ),
    )

    steps_file = tmp_path / "steps.txt"
    steps_file.write_text("1. step\n", encoding="utf-8")

    cluster_manage_mod._cmd_cluster_create(
        argparse.Namespace(
            cluster_name="alpha",
            description="desc",
            action="do",
            priority=3,
            steps_file=str(steps_file),
        )
    )
    out_create = capsys.readouterr().out
    assert "Created cluster: alpha" in out_create
    assert plan["clusters"]["alpha"]["priority"] == 3
    assert plan["clusters"]["alpha"]["action_steps"] == [{"title": "step"}]

    plan["clusters"]["alpha"]["action_steps"] = [{"title": "A"}]
    cluster_manage_mod._cmd_cluster_export(
        argparse.Namespace(cluster_name="alpha", export_format="yaml")
    )
    out_export = capsys.readouterr().out
    assert "clusters:" in out_export
    assert "name: alpha" in out_export

    import_file = tmp_path / "clusters.yaml"
    import_file.write_text(
        "clusters:\n"
        "  - name: new-cluster\n"
        "    description: imported\n"
        "    steps:\n"
        "      - title: first\n",
        encoding="utf-8",
    )
    cluster_manage_mod._cmd_cluster_import(
        argparse.Namespace(file=str(import_file), dry_run=True)
    )
    out_import = capsys.readouterr().out
    assert "[CREATE] new-cluster" in out_import

    monkeypatch.setattr(
        cluster_manage_mod,
        "merge_clusters",
        lambda _plan, _source, _target: (2, ["i1", "i2"]),
    )
    cluster_manage_mod._cmd_cluster_merge(
        argparse.Namespace(source="alpha", target="beta")
    )
    out_merge = capsys.readouterr().out
    assert "Merged cluster 'alpha' into 'beta'" in out_merge


def test_cluster_manage_yaml_dependency_hint(monkeypatch, tmp_path, capsys) -> None:
    plan = {
        "clusters": {
            "alpha": {
                "action_steps": [{"title": "A"}],
            }
        }
    }
    monkeypatch.setattr(cluster_manage_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(
        cluster_manage_mod,
        "_import_yaml_module",
        lambda: (
            print(
                '  YAML import/export requires PyYAML. Install with: pip install "desloppify[plan-yaml]"'
            )
            or None
        ),
    )

    cluster_manage_mod._cmd_cluster_export(
        argparse.Namespace(cluster_name="alpha", export_format="yaml")
    )
    out_export = capsys.readouterr().out
    assert "requires PyYAML" in out_export
    assert "desloppify[plan-yaml]" in out_export

    import_file = tmp_path / "clusters.yaml"
    import_file.write_text("clusters: []\n", encoding="utf-8")
    cluster_manage_mod._cmd_cluster_import(
        argparse.Namespace(file=str(import_file), dry_run=True)
    )
    out_import = capsys.readouterr().out
    assert "requires PyYAML" in out_import
    assert "desloppify[plan-yaml]" in out_import


def test_cluster_reorder_item_position_and_whole_cluster_paths(monkeypatch, capsys) -> None:
    no_move = cluster_reorder_mod._resolve_item_position(
        "top",
        None,
        ["i1"],
        ["i1", "i2"],
        {"i1", "i2"},
        "alpha",
        state={},
        plan={},
    )
    assert no_move is None
    assert "Already at the top" in capsys.readouterr().out

    invalid_offset = cluster_reorder_mod._resolve_item_position(
        "up",
        "oops",
        ["i1"],
        ["i1", "i2"],
        {"i1", "i2"},
        "alpha",
        state={},
        plan={},
    )
    assert invalid_offset is None

    valid_offset = cluster_reorder_mod._resolve_item_position(
        "down",
        "3",
        ["i1"],
        ["i1", "i2"],
        {"i1", "i2"},
        "alpha",
        state={},
        plan={},
    )
    assert valid_offset == ("down", None, 3)

    plan = {
        "queue_order": ["i1", "i2"],
        "clusters": {
            "alpha": {"issue_ids": ["i1"]},
            "beta": {"issue_ids": ["i2"]},
        },
    }
    monkeypatch.setattr(cluster_reorder_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(cluster_reorder_mod, "resolve_target", lambda _p, t, _pos: t)
    monkeypatch.setattr(cluster_reorder_mod, "move_items", lambda _p, items, *_a, **_k: len(items))
    monkeypatch.setattr(cluster_reorder_mod, "append_log_entry", lambda *_a, **_k: None)
    monkeypatch.setattr(cluster_reorder_mod, "save_plan", lambda *_a, **_k: None)

    cluster_reorder_mod._cmd_cluster_reorder(
        argparse.Namespace(
            cluster_names="alpha,beta",
            cluster_name="",
            position="top",
            target=None,
            item_pattern=None,
        )
    )
    out_whole = capsys.readouterr().out
    assert "Moved cluster(s) alpha, beta" in out_whole

    cluster_reorder_mod._cmd_cluster_reorder(
        argparse.Namespace(
            cluster_names="alpha,beta",
            cluster_name="",
            position="top",
            target=None,
            item_pattern="i1",
        )
    )
    out_item = capsys.readouterr().out
    assert "--item requires exactly one cluster name" in out_item


def test_cluster_dispatch_suggest_close_matches_supports_hash_and_slug(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cluster_dispatch_mod, "colorize", lambda text, _tone: text)
    state = {
        "issues": {
            "review::src/a.py::timing_attack::f41b3eb7": {},
            "review::src/b.py::naming_issue::c1d2e3f4": {},
        }
    }
    plan = {
        "queue_order": ["review::src/c.py::other_issue::11111111"],
        "clusters": {"alpha": {"issue_ids": ["review::src/d.py::sluggy::22222222"]}},
    }

    cluster_dispatch_mod._suggest_close_matches(
        state,
        plan,
        ["f41b3eb7", "review::src/a.py::timing_attack"],
    )
    out = capsys.readouterr().out
    assert "match by hash suffix alone: f41b3eb7" in out
    assert "review::src/a.py::timing_attack::f41b3eb7" in out


def test_cluster_update_direct_paths(capsys) -> None:
    plan = {
        "clusters": {
            "alpha": {"issue_ids": [], "action_steps": [{"title": "one"}]},
            "beta": {"issue_ids": []},
        }
    }
    saved: list[dict] = []

    args = argparse.Namespace(
        cluster_name="alpha",
        description="updated",
        steps=None,
        steps_file=None,
        add_step="two",
        detail="detail",
        update_step=None,
        remove_step=None,
        done_step=1,
        undone_step=None,
        priority=1,
        effort="small",
        depends_on=["beta"],
        issue_refs=["i1"],
    )
    services = cluster_update_flow_mod.ClusterUpdateServices(
        load_plan_fn=lambda: plan,
        save_plan_fn=lambda payload: saved.append(payload),
        append_log_entry_fn=lambda *_a, **_k: None,
        parse_steps_file_fn=lambda _text: [],
        normalize_step_fn=lambda step: {"title": str(step)},
        step_summary_fn=lambda step: str(step),
        utc_now_fn=lambda: "2026-03-09T00:00:00+00:00",
        colorize_fn=lambda text, _tone: text,
    )
    cluster_update_mod.cmd_cluster_update(
        args,
        services=services,
        plan_lock_fn=lambda: nullcontext(),
    )
    out = capsys.readouterr().out
    assert "Updated cluster: alpha" in out
    cluster = plan["clusters"]["alpha"]
    assert cluster["description"] == "updated"
    assert cluster["priority"] == 1
    assert cluster["depends_on_clusters"] == ["beta"]
    assert cluster["action_steps"][0]["done"] is True
    assert cluster["action_steps"][1]["title"] == "two"
    assert cluster["action_steps"][1]["issue_refs"] == ["i1"]
    assert saved

    no_update_args = argparse.Namespace(
        cluster_name="alpha",
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
        depends_on=None,
        issue_refs=None,
    )
    cluster_update_mod.cmd_cluster_update(
        no_update_args,
        services=cluster_update_flow_mod.ClusterUpdateServices(
            load_plan_fn=lambda: plan,
            save_plan_fn=lambda _payload: None,
            append_log_entry_fn=lambda *_a, **_k: None,
            parse_steps_file_fn=lambda _text: [],
            normalize_step_fn=lambda step: {"title": str(step)},
            step_summary_fn=lambda step: str(step),
            utc_now_fn=lambda: "2026-03-09T00:00:00+00:00",
            colorize_fn=lambda text, _tone: text,
        ),
        plan_lock_fn=lambda: nullcontext(),
    )
    out2 = capsys.readouterr().out
    assert "Nothing to update" in out2


def test_cluster_update_steps_file_parse_failure_raises_command_error(tmp_path) -> None:
    plan = {"clusters": {"alpha": {"issue_ids": [], "action_steps": []}}}
    steps_file = tmp_path / "steps.md"
    steps_file.write_text("1. bad step", encoding="utf-8")

    args = argparse.Namespace(
        cluster_name="alpha",
        description=None,
        steps=None,
        steps_file=str(steps_file),
        add_step=None,
        detail=None,
        update_step=None,
        remove_step=None,
        done_step=None,
        undone_step=None,
        priority=None,
        effort=None,
        depends_on=None,
        issue_refs=None,
    )
    services = cluster_update_flow_mod.ClusterUpdateServices(
        load_plan_fn=lambda: plan,
        save_plan_fn=lambda _payload: None,
        append_log_entry_fn=lambda *_a, **_k: None,
        parse_steps_file_fn=lambda _text: (_ for _ in ()).throw(ValueError("invalid format")),
        normalize_step_fn=lambda step: {"title": str(step)},
        step_summary_fn=lambda step: str(step),
        utc_now_fn=lambda: "2026-03-09T00:00:00+00:00",
        colorize_fn=lambda text, _tone: text,
    )

    with pytest.raises(CommandError, match="failed to load steps file"):
        cluster_update_mod.cmd_cluster_update(
            args,
            services=services,
            plan_lock_fn=lambda: nullcontext(),
        )
