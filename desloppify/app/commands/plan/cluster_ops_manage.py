"""Cluster create/delete/import/export/merge handlers."""

from __future__ import annotations

import argparse
from pathlib import Path

from desloppify.base.output.terminal import colorize
from desloppify.engine.plan import (
    append_log_entry,
    create_cluster,
    delete_cluster,
    format_steps,
    load_plan,
    merge_clusters,
    normalize_step,
    parse_steps_file,
    save_plan,
)
from desloppify.state import utc_now


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
        path = Path(steps_file)
        if not path.is_file():
            print(colorize(f"  Steps file not found: {steps_file}", "red"))
            return
        steps = parse_steps_file(path.read_text())
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
        import yaml  # noqa: PLC0415

        data = {
            "clusters": [
                {
                    "name": cluster_name,
                    "description": cluster.get("description") or "",
                    **({"priority": cluster["priority"]} if "priority" in cluster else {}),
                    "steps": [normalize_step(step) for step in steps],
                }
            ]
        }
        print(yaml.dump(data, default_flow_style=False, sort_keys=False))
    else:
        print(format_steps(steps))


def _cmd_cluster_import(args: argparse.Namespace) -> None:
    """Bulk create/update clusters from a YAML file."""
    file_path: str = getattr(args, "file", "")
    dry_run: bool = getattr(args, "dry_run", False)

    path = Path(file_path)
    if not path.is_file():
        print(colorize(f"  File not found: {file_path}", "red"))
        return

    import yaml  # noqa: PLC0415

    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or "clusters" not in data:
        print(colorize("  Invalid YAML: expected top-level 'clusters' key.", "red"))
        return

    entries = data["clusters"]
    if not isinstance(entries, list):
        print(colorize("  Invalid YAML: 'clusters' must be a list.", "red"))
        return

    plan = load_plan()
    clusters = plan.get("clusters", {})
    created = 0
    updated = 0

    for entry in entries:
        if not isinstance(entry, dict) or "name" not in entry:
            print(colorize(f"  Skipping entry without 'name': {entry!r}", "yellow"))
            continue
        name = entry["name"]
        is_new = name not in clusters

        if dry_run:
            action = "CREATE" if is_new else "UPDATE"
            step_count = len(entry.get("steps", []))
            print(colorize(f"  [{action}] {name}: {step_count} step(s)", "cyan"))
            continue

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
            imported_steps = []
            for step in entry["steps"]:
                if isinstance(step, str):
                    imported_steps.append({"title": step})
                elif isinstance(step, dict):
                    imported: dict = {"title": step.get("title", "")}
                    if "detail" in step:
                        imported["detail"] = step["detail"]
                    if "refs" in step:
                        imported["issue_refs"] = step["refs"]
                    elif "issue_refs" in step:
                        imported["issue_refs"] = step["issue_refs"]
                    imported_steps.append(imported)
            cluster["action_steps"] = imported_steps
        cluster["user_modified"] = True
        cluster["updated_at"] = utc_now()

    if dry_run:
        print(colorize("  (dry run — no changes saved)", "dim"))
        return

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
