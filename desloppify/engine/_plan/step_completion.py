"""Auto-complete action steps from fixed resolve evidence."""

from __future__ import annotations


def _fixed_resolved_ids(plan: dict) -> set[str]:
    """Return IDs with a recorded fixed resolve, including legacy entries."""
    fixed_ids: set[str] = set()
    execution_log = plan.get("execution_log")
    if not isinstance(execution_log, list):
        return fixed_ids

    for entry in execution_log:
        if not isinstance(entry, dict) or entry.get("action") != "resolve":
            continue
        detail = entry.get("detail")
        if isinstance(detail, dict) and detail.get("status") != "fixed":
            continue
        issue_ids = entry.get("issue_ids")
        if isinstance(issue_ids, list):
            fixed_ids.update(
                issue_id for issue_id in issue_ids if isinstance(issue_id, str)
            )
    return fixed_ids


def auto_complete_steps(plan: dict) -> list[str]:
    """Mark steps done when every issue ref has a fixed resolve record.

    A skipped issue is deliberately absent from ``queue_order``, but its work
    has not been completed.  A disposition, queue change, or workflow event is
    therefore not enough to complete a referenced action step.

    Returns list of human-readable messages for completed steps.
    """
    messages: list[str] = []
    fixed_ids = _fixed_resolved_ids(plan)

    for name, cluster in plan.get("clusters", {}).items():
        for i, step in enumerate(cluster.get("action_steps") or []):
            if not isinstance(step, dict) or step.get("done"):
                continue
            refs = step.get("issue_refs", [])
            if not refs:
                continue
            # Match by suffix: ref "abc123" matches "review::path::abc123".
            all_fixed = all(
                any(issue_id.endswith(ref) or issue_id == ref for issue_id in fixed_ids)
                for ref in refs
            )
            if all_fixed:
                step["done"] = True
                messages.append(
                    f"  Step {i + 1} of '{name}' auto-completed: {step.get('title', '')}"
                )
    return messages


__all__ = ["auto_complete_steps"]
