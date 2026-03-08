"""Cluster action-step rendering helpers."""

from __future__ import annotations


def print_step(i: int, step: str | dict, *, colorize_fn) -> None:
    """Print a single step with title, detail, refs, and done status."""
    if isinstance(step, str):
        print(colorize_fn(f"    {i}. {step}", "dim"))
        return
    done = step.get("done", False)
    marker = "[x]" if done else "[ ]"
    title = step.get("title", "")
    print(f"    {i}. {marker} {title}")
    if done:
        print(colorize_fn("         (completed)", "dim"))
        return
    detail = step.get("detail", "")
    if detail:
        for line in detail.splitlines():
            print(colorize_fn(f"         {line}", "dim"))
    refs = step.get("issue_refs", [])
    if refs:
        print(colorize_fn(f"         Refs: {', '.join(refs)}", "dim"))


__all__ = ["print_step"]
