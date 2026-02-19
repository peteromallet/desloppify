"""issues command: state-backed work queue for review findings."""

import sys
from pathlib import Path

from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.helpers.rendering import print_agent_plan
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.core.issues_render import finding_weight, render_issue_detail
from desloppify.engine.work_queue_internal.issues import (
    impact_label,
    list_open_review_findings,
    update_investigation,
)
from desloppify.intelligence.narrative import NarrativeContext, compute_narrative
from desloppify.state import save_state
from desloppify.utils import colorize


def cmd_issues(args):
    """Dispatch to list/show/update based on subcommand."""
    action = getattr(args, "issues_action", None)
    if action in (None, "list"):
        _list_issues(args)
    elif action == "show":
        _show_issue(args)
    elif action == "update":
        _update_issue(args)


def _score_for_issue(finding, assessments, weight_fn, label_fn) -> str:
    """Render score cell as '<assessment> <impact>'."""
    dim = finding.get("detail", {}).get("dimension", "")
    raw_score = assessments.get(dim)
    score = f"{float(raw_score):.1f}" if isinstance(raw_score, int | float) else "--.-"
    weight, _, _ = weight_fn(finding)
    return f"{score} {label_fn(weight)}"


def _list_issues(args):
    """Print numbered table of open review findings."""
    state = command_runtime(args).state
    narrative = compute_narrative(state, context=NarrativeContext(command="issues"))
    items = list_open_review_findings(state)

    if not items:
        print(colorize("\n  No review findings open.\n", "dim"))
        print(
            colorize(
                "  Next command: `desloppify review --prepare --holistic --refresh`",
                "dim",
            )
        )
        print()
        write_query(
            {
                "command": "issues",
                "action": "list",
                "items": [],
                "next_command": "desloppify review --prepare --holistic --refresh",
                "narrative": narrative,
            }
        )
        return

    print(
        colorize(
            f"\n  {len(items)} open review finding{'s' if len(items) != 1 else ''} "
            f"(highest impact first)\n",
            "bold",
        )
    )

    assessments = state.get("subjective_assessments") or {}
    # Table header
    print(f"  {'#':<4} {'Score':<8} {'Dimension':<28} {'Summary':<50} {'Investigated'}")
    print(f"  {'─' * 4} {'─' * 8} {'─' * 28} {'─' * 50} {'─' * 12}")

    for i, f in enumerate(items, 1):
        score_str = _score_for_issue(f, assessments, finding_weight, impact_label)
        dim = f.get("detail", {}).get("dimension", "unknown").replace("_", " ")
        summary = f.get("summary", "")[:50]
        investigated = "yes" if f.get("detail", {}).get("investigation") else "no"
        print(f"  {i:<4} {score_str:<8} {dim:<28} {summary:<50} {investigated}")

    uninvestigated = sum(
        1 for f in items if not f.get("detail", {}).get("investigation")
    )
    print()
    if uninvestigated:
        print(colorize(f"  {uninvestigated} need investigation.", "dim"))
    print_agent_plan(
        [
            "Read one issue deeply: `desloppify issues show 1`",
            "Add investigation notes: `desloppify issues update 1 --file analysis.md`",
            "Fix and resolve the finding",
        ],
        next_command="desloppify issues show 1",
    )
    print()

    write_query(
        {
            "command": "issues",
            "action": "list",
            "count": len(items),
            "items": [
                {
                    "id": f["id"],
                    "summary": f.get("summary", ""),
                    "dimension": f.get("detail", {}).get("dimension", ""),
                    "investigated": bool(f.get("detail", {}).get("investigation")),
                }
                for f in items
            ],
            "next_command": "desloppify issues show 1",
            "narrative": narrative,
        }
    )


def _show_issue(args):
    """Show full details for a single issue by number."""
    state = command_runtime(args).state
    narrative = compute_narrative(state, context=NarrativeContext(command="issues"))
    items = list_open_review_findings(state)
    number = args.number

    if not items:
        print(colorize("\n  No review findings open.\n", "dim"))
        return

    if number < 1 or number > len(items):
        print(
            colorize(f"\n  Issue #{number} out of range (1–{len(items)}).\n", "red"),
            file=sys.stderr,
        )
        return

    finding = items[number - 1]
    lang = resolve_lang(args)
    lang_name = lang.name if lang else finding.get("lang", "unknown")

    assessments = state.get("subjective_assessments") or {}
    doc = render_issue_detail(
        finding, lang_name, number=number, subjective_assessments=assessments
    )
    print()
    print(doc)

    write_query(
        {
            "command": "issues",
            "action": "show",
            "number": number,
            "finding": {
                "id": finding["id"],
                "summary": finding.get("summary", ""),
                "detail": finding.get("detail", {}),
            },
            "next_command": f'desloppify resolve fixed "{finding["id"]}" --note "<what you fixed>"',
            "narrative": narrative,
        }
    )


def _update_issue(args):
    """Add investigation notes to an issue."""
    runtime = command_runtime(args)
    state = runtime.state
    sp = runtime.state_path
    narrative = compute_narrative(state, context=NarrativeContext(command="issues"))
    items = list_open_review_findings(state)
    number = args.number

    if not items:
        print(colorize("\n  No review findings open.\n", "dim"))
        return

    if number < 1 or number > len(items):
        print(
            colorize(f"\n  Issue #{number} out of range (1–{len(items)}).\n", "red"),
            file=sys.stderr,
        )
        return

    finding = items[number - 1]
    file_path = Path(args.file)
    if not file_path.exists():
        print(colorize(f"\n  File not found: {args.file}\n", "red"), file=sys.stderr)
        return

    try:
        text = file_path.read_text()
    except OSError as e:
        print(colorize(f"\n  Could not read file: {e}\n", "red"), file=sys.stderr)
        return

    ok = update_investigation(state, finding["id"], text)
    if not ok:
        print(
            colorize(f"\n  Could not update issue #{number}.\n", "red"), file=sys.stderr
        )
        return

    save_state(state, sp)
    lang = resolve_lang(args)
    lang_name = lang.name if lang else finding.get("lang", "unknown")
    print(colorize(f"\n  Investigation saved for issue #{number}.", "green"))
    print(
        colorize(
            f'  Fix the issue, then: desloppify --lang {lang_name} resolve fixed "{finding["id"]}"',
            "dim",
        )
    )
    print(colorize("  Next command: `desloppify issues show 1`", "dim"))
    print()
    write_query(
        {
            "command": "issues",
            "action": "update",
            "number": number,
            "finding_id": finding["id"],
            "next_command": f'desloppify --lang {lang_name} resolve fixed "{finding["id"]}"',
            "narrative": narrative,
        }
    )
