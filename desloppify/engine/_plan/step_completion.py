"""Auto-complete action steps once their referenced work is no longer pending."""

from __future__ import annotations


def auto_complete_steps(plan: dict) -> list[str]:
    """Mark steps done once refs leave both the queue and temporary deferrals.

    Returns list of human-readable messages for completed steps.
    """
    messages: list[str] = []
    pending_ids = set(plan.get("queue_order", []))
    pending_ids.update(
        issue_id
        for issue_id, entry in plan.get("skipped", {}).items()
        if isinstance(entry, dict) and entry.get("kind") == "temporary"
    )

    for name, cluster in plan.get("clusters", {}).items():
        for i, step in enumerate(cluster.get("action_steps") or []):
            if not isinstance(step, dict) or step.get("done"):
                continue
            refs = step.get("issue_refs", [])
            if not refs:
                continue
            # Match by suffix: ref "abc123" matches "review::path::abc123"
            all_gone = all(
                not any(qid.endswith(ref) or qid == ref for qid in pending_ids)
                for ref in refs
            )
            if all_gone:
                step["done"] = True
                messages.append(
                    f"  Step {i + 1} of '{name}' auto-completed: {step.get('title', '')}"
                )
    return messages


__all__ = ["auto_complete_steps"]
