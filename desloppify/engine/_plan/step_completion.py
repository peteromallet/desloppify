"""Auto-complete action steps when their referenced issues leave the queue."""

from __future__ import annotations


def auto_complete_steps(
    plan: dict,
    *,
    resolved_refs: set[str] | None = None,
    open_refs: set[str] | None = None,
) -> list[str]:
    """Mark steps done when all their issue_refs are no longer in the queue.

    Returns list of human-readable messages for completed steps.
    """
    messages: list[str] = []
    queue_set = set(plan.get("queue_order", []))

    for name, cluster in plan.get("clusters", {}).items():
        for i, step in enumerate(cluster.get("action_steps") or []):
            if not isinstance(step, dict) or step.get("done"):
                continue
            refs = step.get("issue_refs", [])
            if not refs:
                continue
            if resolved_refs is not None and not any(ref in resolved_refs for ref in refs):
                continue
            if open_refs is not None:
                all_gone = all(ref not in open_refs for ref in refs)
            else:
                # Match by suffix: ref "abc123" matches "review::path::abc123"
                all_gone = all(
                    not any(qid.endswith(ref) or qid == ref for qid in queue_set)
                    for ref in refs
                )
            if all_gone:
                step["done"] = True
                messages.append(
                    f"  Step {i + 1} of '{name}' auto-completed: {step.get('title', '')}"
                )
    return messages


__all__ = ["auto_complete_steps"]
