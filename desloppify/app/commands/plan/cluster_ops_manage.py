"""Cluster create/delete/import/export/merge handlers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from desloppify.base.output.terminal import colorize
from desloppify.engine.plan_state import (
    load_plan,
    save_plan,
)
from desloppify.engine.plan_ops import (
    append_log_entry,
    create_cluster,
    delete_cluster,
    format_steps,
    merge_clusters,
    normalize_step,
    parse_steps_file,
)
from desloppify.state_io import utc_now


def _import_yaml_module() -> Any | None:
    """Load optional YAML dependency for cluster import/export commands."""
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        print(
            colorize(
                "  YAML import/export requires PyYAML. "
                "Install with: pip install \"desloppify[plan-yaml]\"",
                "red",
            )
        )
        return None
    return yaml


def _load_steps_from_file(steps_file: str) -> list[dict] | None:
    path = Path(steps_file)
    if not path.is_file():
        print(colorize(f"  Steps file not found: {steps_file}", "red"))
        return None
    return parse_steps_file(path.read_text())


def _load_cluster_import_entries(file_path: str, *, yaml_module) -> list[dict] | None:
    path = Path(file_path)
    if not path.is_file():
        print(colorize(f"  File not found: {file_path}", "red"))
        return None
    data = yaml_module.safe_load(path.read_text())
    if not isinstance(data, dict) or "clusters" not in data:
        print(colorize("  Invalid YAML: expected top-level 'clusters' key.", "red"))
        return None
    entries = data["clusters"]
    if not isinstance(entries, list):
        print(colorize("  Invalid YAML: 'clusters' must be a list.", "red"))
        return None
    return entries


def _imported_cluster_steps(entry: dict) -> list[dict]:
    imported_steps: list[dict] = []
    for step in entry.get("steps", []):
        if isinstance(step, str):
            imported_steps.append({"title": step})
            continue
        if not isinstance(step, dict):
            continue
        imported: dict = {"title": step.get("title", "")}
        if "detail" in step:
            imported["detail"] = step["detail"]
        if "refs" in step:
            imported["issue_refs"] = step["refs"]
        elif "issue_refs" in step:
            imported["issue_refs"] = step["issue_refs"]
        imported_steps.append(imported)
    return imported_steps


def _cmd_cluster_create(args: argparse.Namespace) -> None:
    name: str = getattr(args, "cluster_name", "")
    description: str | None = getattr(args, "description", None)
    action: str | None = getattr(args, "action", None)
    priority: int | None = getattr(args, "priority", None)
    steps_file: str | None = getattr(args, "steps_file", None)

    plan = load_plan()
    try:
        cluster = create_cluster(plan, name, description, action=action)
    except ValueError as ex:
        print(colorize(f"  {ex}", "red"))
        return

    if priority is not None:
        cluster["priority"] = priority
    if steps_file is not None:
        steps = _load_steps_from_file(steps_file)
        if steps is None:
            return
        cluster["action_steps"] = steps
        print(colorize(f"  Loaded {len(steps)} step(s) from {steps_file}", "dim"))

    append_log_entry(
        plan,
        "cluster_create",
        cluster_name=name,
        actor="user",
        detail={"description": description, "action": action},
    )
    save_plan(plan)
    print(colorize(f"  Created cluster: {name}", "green"))


def _cmd_cluster_delete(args: argparse.Namespace) -> None:
    cluster_name: str = getattr(args, "cluster_name", "")
    plan = load_plan()
    try:
        orphaned = delete_cluster(plan, cluster_name)
    except ValueError as ex:
        print(colorize(f"  {ex}", "red"))
        return
    append_log_entry(
        plan,
        "cluster_delete",
        issue_ids=orphaned,
        cluster_name=cluster_name,
        actor="user",
    )
    save_plan(plan)
    print(colorize(f"  Deleted cluster {cluster_name} ({len(orphaned)} items orphaned).", "green"))


def _cmd_cluster_export(args: argparse.Namespace) -> None:
    """Export cluster steps to stdout in text or YAML format."""
    cluster_name: str = getattr(args, "cluster_name", "")
    export_format: str = getattr(args, "export_format", "text")

    plan = load_plan()
    cluster = plan.get("clusters", {}).get(cluster_name)
    if cluster is None:
        print(colorize(f"  Cluster {cluster_name!r} does not exist.", "red"))
        return

    steps = cluster.get("action_steps") or []
    if not steps:
        print(colorize("  No steps to export.", "yellow"))
        return

    if export_format == "yaml":
        yaml = _import_yaml_module()
        if yaml is None:
            return

        payload: dict[str, object] = {
            "name": cluster_name,
            "description": cluster.get("description") or "",
            "steps": [normalize_step(step) for step in steps],
        }
        if "priority" in cluster:
            payload["priority"] = cluster["priority"]
        print(yaml.dump({"clusters": [payload]}, default_flow_style=False, sort_keys=False))
    else:
        print(format_steps(steps))


def _cmd_cluster_import(args: argparse.Namespace) -> None:
    """Bulk create/update clusters from a YAML file."""
    file_path: str = getattr(args, "file", "")
    dry_run: bool = getattr(args, "dry_run", False)

    yaml = _import_yaml_module()
    if yaml is None:
        return

    entries = _load_cluster_import_entries(file_path, yaml_module=yaml)
    if entries is None:
        return

    plan = load_plan()
    clusters = plan.get("clusters", {})

    if dry_run:
        for entry in entries:
            if not isinstance(entry, dict) or "name" not in entry:
                print(colorize(f"  Skipping entry without 'name': {entry!r}", "yellow"))
                continue
            action = "CREATE" if entry.get("name") not in clusters else "UPDATE"
            step_count = len(entry.get("steps", []))
            print(colorize(f"  [{action}] {entry['name']}: {step_count} step(s)", "cyan"))
        print(colorize("  (dry run — no changes saved)", "dim"))
        return

    created = 0
    updated = 0
    for entry in entries:
        if not isinstance(entry, dict) or "name" not in entry:
            print(colorize(f"  Skipping entry without 'name': {entry!r}", "yellow"))
            continue
        name = entry["name"]
        is_new = name not in clusters

        if is_new:
            try:
                cluster = create_cluster(plan, name, entry.get("description"))
            except ValueError as ex:
                print(colorize(f"  {ex}", "red"))
                continue
            created += 1
        else:
            cluster = clusters[name]
            updated += 1

        if "description" in entry:
            cluster["description"] = entry["description"]
        if "priority" in entry:
            cluster["priority"] = entry["priority"]
        if "steps" in entry:
            cluster["action_steps"] = _imported_cluster_steps(entry)
        cluster["user_modified"] = True
        cluster["updated_at"] = utc_now()

    save_plan(plan)
    print(colorize(f"  Import complete: {created} created, {updated} updated.", "green"))


def _cmd_cluster_merge(args: argparse.Namespace) -> None:
    """Merge source cluster into target cluster."""
    source: str = getattr(args, "source", "")
    target: str = getattr(args, "target", "")

    plan = load_plan()
    try:
        added, source_ids = merge_clusters(plan, source, target)
    except ValueError as ex:
        print(colorize(f"  {ex}", "red"))
        return

    append_log_entry(
        plan,
        "cluster_merge",
        issue_ids=source_ids,
        cluster_name=target,
        actor="user",
        detail={"source": source, "added": added},
    )
    save_plan(plan)
    print(
        colorize(
            f"  Merged cluster {source!r} into {target!r}: "
            f"{added} issue(s) added, {len(source_ids)} total moved. Source deleted.",
            "green",
        )
    )


__all__ = [
    "_cmd_cluster_create",
    "_cmd_cluster_delete",
    "_cmd_cluster_export",
    "_cmd_cluster_import",
    "_cmd_cluster_merge",
]
