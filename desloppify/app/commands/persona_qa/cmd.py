"""CLI handler for persona-based browser QA."""

from __future__ import annotations

import argparse
import json
import sys

from desloppify.app.commands.helpers.command_runtime import command_runtime
from desloppify.base.output.terminal import colorize
from desloppify.state_io import save_state


def _do_prepare(args: argparse.Namespace) -> None:
    """Print structured agent instructions for persona QA testing."""
    from .profiles import load_all_profiles

    url = getattr(args, "url", None)
    if not url:
        print(colorize("Error: --url is required for --prepare", "red"))
        sys.exit(1)

    persona_filter = getattr(args, "persona", None)
    profiles = load_all_profiles(persona_filter=persona_filter)

    for profile in profiles:
        name = profile["name"]
        desc = profile.get("description", "")
        device = profile.get("device", "desktop")
        viewport = profile.get("viewport", {"width": 1280, "height": 720})
        vw, vh = viewport.get("width", 1280), viewport.get("height", 720)

        print(colorize(f"\n{'=' * 60}", "cyan"))
        print(colorize(f"  PERSONA QA: {name}", "bold"))
        print(colorize(f"{'=' * 60}", "cyan"))
        print(f"  URL: {url}")
        print(f"  Device: {device} ({vw}x{vh})")
        print(f"\n  Description:\n    {desc}")

        skip_routes = profile.get("skip_routes", [])
        if skip_routes:
            print(f"\n  Skip routes: {', '.join(skip_routes)}")

        for i, scenario in enumerate(profile.get("scenarios", []), 1):
            print(colorize(f"\n  SCENARIO {i}: {scenario['name']}", "bold"))
            print(f"  Start: {scenario['start']}")
            max_steps = scenario.get("max_steps", 10)
            print(f"  Max steps: {max_steps}")
            print(f"  Goal:\n    {scenario['goal'].strip()}")
            print(f"\n  CHECK ITEMS:")
            for j, check in enumerate(scenario.get("check", []), 1):
                print(f"    {j}. {check}")

        accessibility = profile.get("accessibility", [])
        if accessibility:
            print(colorize(f"\n  ACCESSIBILITY CHECKS:", "bold"))
            for j, check in enumerate(accessibility, 1):
                print(f"    {j}. {check}")

        severity_mapping = profile.get("severity_mapping", {
            "blocker": "high",
            "usability": "medium",
            "polish": "low",
        })
        print(f"\n  Severity mapping: {json.dumps(severity_mapping)}")

        print(colorize(f"\n  INSTRUCTIONS FOR AGENT:", "bold"))
        print(f"  1. Open {url}{profile['scenarios'][0]['start']} in the browser with {device} viewport ({vw}x{vh})")
        print(f"  2. Act as this persona — navigate naturally toward each goal")
        print(f"  3. For each check item, evaluate pass/fail with evidence")
        print(f"  4. Take screenshots of any failures")
        print(f"  5. When done, save findings as JSON and import with:")
        print(colorize(f"     desloppify persona-qa --import <findings.json>", "cyan"))

        print(colorize(f"\n  FINDINGS JSON FORMAT:", "bold"))
        example = {
            "persona": name,
            "base_url": url,
            "tested_at": "ISO-8601 timestamp",
            "scenarios": [
                {
                    "name": "scenario name",
                    "route": "/path",
                    "checks": [
                        {
                            "check": "check item text",
                            "passed": False,
                            "severity": "blocker|usability|polish",
                            "evidence": "what was observed",
                            "screenshot": "optional/path.png",
                        }
                    ],
                }
            ],
        }
        print(f"    {json.dumps(example, indent=2)}")


def _do_import(args: argparse.Namespace) -> None:
    """Import findings JSON into state."""
    from .findings import import_findings

    findings_path = getattr(args, "import_file", None)
    if not findings_path:
        print(colorize("Error: --import requires a findings JSON path", "red"))
        sys.exit(1)

    rt = command_runtime(args)
    created, updated, auto_resolved = import_findings(findings_path, rt.state)
    save_state(rt.state, rt.state_path)

    print(colorize(f"\n  Persona QA import complete:", "bold"))
    print(f"    Created:       {created}")
    print(f"    Updated:       {updated}")
    print(f"    Auto-resolved: {auto_resolved}")


def _do_status(args: argparse.Namespace) -> None:
    """Show per-persona QA status summary."""
    rt = command_runtime(args)
    issues = rt.state.get("work_items", {})

    # Group persona_qa issues by persona
    personas: dict[str, dict[str, int]] = {}
    for issue_id, issue in issues.items():
        if issue.get("detector") != "persona_qa":
            continue
        detail = issue.get("detail", {})
        persona = detail.get("persona", "unknown")
        if persona not in personas:
            personas[persona] = {"open": 0, "fixed": 0, "auto_resolved": 0, "total": 0}
        personas[persona]["total"] += 1
        status = issue.get("status", "open")
        if status == "open":
            personas[persona]["open"] += 1
        elif status == "fixed":
            personas[persona]["fixed"] += 1
        elif status == "auto_resolved":
            personas[persona]["auto_resolved"] += 1

    if not personas:
        print(colorize("\n  No persona QA findings in state.", "dim"))
        print("  Run: desloppify persona-qa --prepare --url <base_url>")
        return

    print(colorize(f"\n  Persona QA Status", "bold"))
    print(colorize("  " + "─" * 50, "dim"))
    for persona, counts in sorted(personas.items()):
        passing = counts["total"] - counts["open"]
        print(
            f"  {persona}: {passing}/{counts['total']} passing "
            f"({counts['open']} open, {counts['fixed']} fixed, "
            f"{counts['auto_resolved']} auto-resolved)"
        )


def _do_clear(args: argparse.Namespace) -> None:
    """Remove all persona_qa findings from state."""
    rt = command_runtime(args)
    issues = rt.state.get("work_items", {})
    to_remove = [
        issue_id
        for issue_id, issue in issues.items()
        if issue.get("detector") == "persona_qa"
    ]
    for issue_id in to_remove:
        del issues[issue_id]
    save_state(rt.state, rt.state_path)
    print(colorize(f"\n  Cleared {len(to_remove)} persona QA finding(s).", "bold"))


def cmd_persona_qa(args: argparse.Namespace) -> None:
    """Main persona QA command dispatcher."""
    if getattr(args, "clear", False):
        _do_clear(args)
        return
    if getattr(args, "status", False):
        _do_status(args)
        return
    if getattr(args, "import_file", None):
        _do_import(args)
        return
    # Default: --prepare mode (also when just --url is given)
    _do_prepare(args)


__all__ = ["cmd_persona_qa"]
