"""issues command: state-backed work queue for review findings."""

import sys

from ..utils import colorize
from ._helpers import _write_query


def cmd_issues(args):
    """Dispatch to list/show/update based on subcommand."""
    action = getattr(args, "issues_action", None)
    if action == "show":
        _show_issue(args)
    elif action == "update":
        _update_issue(args)
    else:
        _list_issues(args)


def _list_issues(args):
    """Print numbered table of open review findings."""
    from ..issues import list_open_review_findings, finding_weight, impact_label

    state = args._preloaded_state
    items = list_open_review_findings(state)

    if not items:
        print(colorize("\n  No review findings open.\n", "dim"))
        _write_query({"command": "issues", "action": "list", "items": []})
        return

    print(colorize(f"\n  {len(items)} open review finding{'s' if len(items) != 1 else ''} "
            f"(highest impact first)\n", "bold"))

    assessments = state.get("subjective_assessments") or state.get("review_assessments") or {}
    # Table header
    print(f"  {'#':<4} {'Score':<8} {'Dimension':<28} {'Summary':<50} {'Investigated'}")
    print(f"  {'─'*4} {'─'*8} {'─'*28} {'─'*50} {'─'*12}")

    for i, f in enumerate(items, 1):
        detail = f.get("detail", {})
        dim_key = detail.get("dimension", "unknown")
        dim = dim_key.replace("_", " ")
        # Show assessment score if available, otherwise impact label
        assessment = assessments.get(dim_key)
        if assessment:
            score_str = f"{assessment['score']}/100"
        else:
            weight, _, _ = finding_weight(f)
            score_str = impact_label(weight)
        summary = f.get("summary", "")[:50]
        investigated = "yes" if detail.get("investigation") else "no"
        print(f"  {i:<4} {score_str:<8} {dim:<28} {summary:<50} {investigated}")

    uninvestigated = sum(1 for f in items if not f.get("detail", {}).get("investigation"))
    print()
    if uninvestigated:
        print(colorize(f"  {uninvestigated} need investigation.", "dim"))
    print(colorize(f"  Show details: desloppify issues show 1", "dim"))
    print()

    _write_query({
        "command": "issues", "action": "list",
        "count": len(items),
        "items": [{"id": f["id"], "summary": f.get("summary", ""),
                   "dimension": f.get("detail", {}).get("dimension", ""),
                   "investigated": bool(f.get("detail", {}).get("investigation"))}
                  for f in items],
    })


def _show_issue(args):
    """Show full details for a single issue by number."""
    from ..issues import list_open_review_findings, render_issue_detail
    from ._helpers import resolve_lang

    state = args._preloaded_state
    items = list_open_review_findings(state)
    number = args.number

    if not items:
        print(colorize("\n  No review findings open.\n", "dim"))
        return

    if number < 1 or number > len(items):
        print(colorize(f"\n  Issue #{number} out of range (1–{len(items)}).\n", "red"),
              file=sys.stderr)
        return

    finding = items[number - 1]
    lang = resolve_lang(args)
    lang_name = lang.name if lang else finding.get("lang", "unknown")

    assessments = state.get("subjective_assessments") or state.get("review_assessments") or {}
    doc = render_issue_detail(finding, lang_name, number=number,
                                subjective_assessments=assessments)
    print()
    print(doc)

    _write_query({
        "command": "issues", "action": "show",
        "number": number,
        "finding": {"id": finding["id"], "summary": finding.get("summary", ""),
                    "detail": finding.get("detail", {})},
    })


def _update_issue(args):
    """Add investigation notes to an issue."""
    from ..issues import list_open_review_findings, update_investigation
    from ..state import save_state
    from ._helpers import resolve_lang
    from pathlib import Path

    state = args._preloaded_state
    sp = args._state_path
    items = list_open_review_findings(state)
    number = args.number

    if not items:
        print(colorize("\n  No review findings open.\n", "dim"))
        return

    if number < 1 or number > len(items):
        print(colorize(f"\n  Issue #{number} out of range (1–{len(items)}).\n", "red"),
              file=sys.stderr)
        return

    file_path = Path(args.file)
    if not file_path.exists():
        print(colorize(f"\n  File not found: {args.file}\n", "red"), file=sys.stderr)
        return

    try:
        text = file_path.read_text()
    except OSError as e:
        print(colorize(f"\n  Could not read file: {e}\n", "red"), file=sys.stderr)
        return

    finding = items[number - 1]
    ok = update_investigation(state, finding["id"], text)
    if not ok:
        print(colorize(f"\n  Could not update issue #{number}.\n", "red"), file=sys.stderr)
        return

    save_state(state, sp)
    lang = resolve_lang(args)
    lang_name = lang.name if lang else finding.get("lang", "unknown")
    print(colorize(f"\n  Investigation saved for issue #{number}.", "green"))
    print(colorize(f"  Fix the issue, then: desloppify --lang {lang_name} resolve fixed \"{finding['id']}\"", "dim"))
    print()
