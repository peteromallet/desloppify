"""Review preparation flow for `desloppify fix review`."""

from __future__ import annotations

import sys
from pathlib import Path

from desloppify import state as state_mod
from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.review import single as review_single_mod
from desloppify.intelligence import review as review_mod
from desloppify.intelligence.integrity import review as subjective_integrity_mod
from desloppify.utils import colorize

from .io import _load_state


def _cmd_fix_review(args):
    """Prepare structured review data with dimension templates for AI evaluation."""
    runtime = command_runtime(args)
    lang_cfg = resolve_lang(args)
    if not lang_cfg:
        print(colorize("Error: could not detect language. Use --lang.", "red"))
        sys.exit(1)

    _sp, state = _load_state(args)
    path = Path(args.path)

    lang_run, found_files = review_single_mod._setup_lang(
        lang_cfg,
        path,
        runtime.config,
    )
    data = review_mod.prepare_review(
        path,
        lang_run,
        state,
        options=review_mod.ReviewPrepareOptions(files=found_files or None),
    )

    if data["total_candidates"] == 0:
        print(
            colorize(
                "\n  All production files have been reviewed. Nothing to do.", "green"
            )
        )
        unassessed_dims = subjective_integrity_mod.unassessed_subjective_dimensions(
            state.get("dimension_scores", {})
        )
        scoped_findings = state_mod.path_scoped_findings(
            state.get("findings", {}),
            state.get("scan_path"),
        )
        _coverage_total, _reasons, holistic_reasons = (
            subjective_integrity_mod.subjective_review_open_breakdown(scoped_findings)
        )
        holistic_open = sum(holistic_reasons.values())
        if unassessed_dims or holistic_open > 0:
            print(colorize("  Subjective integrity still needs refresh.", "yellow"))
            if unassessed_dims:
                rendered = ", ".join(unassessed_dims[:3])
                if len(unassessed_dims) > 3:
                    rendered = f"{rendered}, +{len(unassessed_dims) - 3} more"
                print(colorize(f"    Unassessed (0% placeholder): {rendered}", "dim"))
            if holistic_open > 0:
                print(
                    colorize(
                        f"    Holistic stale/missing signals: {holistic_open}", "dim"
                    )
                )
            print(
                colorize(
                    "    Run: `desloppify review --prepare --holistic --refresh`", "dim"
                )
            )
            print(
                colorize(
                    "    Then import and rescan: `desloppify review --import findings.json --holistic && desloppify scan`",
                    "dim",
                )
            )
        return

    print(
        colorize(f"\n  {data['total_candidates']} files need design review\n", "bold")
    )

    dims = data.get("dimensions", [])
    prompts = data.get("dimension_prompts", {})
    for dim in dims:
        prompt = prompts.get(dim)
        if not prompt:
            continue
        print(colorize(f"  {dim}", "cyan"))
        print(colorize(f"    {prompt['description']}", "dim"))
        print(colorize("    Look for:", "dim"))
        for item in prompt.get("look_for", []):
            print(colorize(f"      - {item}", "dim"))
        skip = prompt.get("skip", [])
        if skip:
            print(colorize("    Skip:", "dim"))
            for item in skip:
                print(colorize(f"      - {item}", "dim"))
        print()

    lang_guide = data.get("lang_guidance") or review_mod.get_lang_guidance(
        lang_run.name
    )
    if lang_guide:
        print(colorize(f"  Language: {lang_run.name}", "cyan"))
        if lang_guide.get("naming"):
            print(colorize(f"    Naming: {lang_guide['naming']}", "dim"))
        for pattern in lang_guide.get("patterns", []):
            print(colorize(f"    - {pattern}", "dim"))
        print()

    write_query(data)
    print(colorize("  Review data written to .desloppify/query.json", "dim"))
    print(colorize("\n  AGENT PLAN (run in order):", "yellow"))
    print(
        colorize(
            "  1. Read query.json — it includes file content, context, and prompts",
            "dim",
        )
    )
    print(colorize("  2. Evaluate each file against the dimensions above", "dim"))
    print(colorize("  3. Save findings as JSON (for example: findings.json)", "dim"))
    print(colorize("  4. Import: desloppify review --import findings.json", "dim"))
    print(
        colorize(
            "  5. Optional objective cross-check: desloppify review --prepare --holistic --refresh",
            "dim",
        )
    )
    print(
        colorize(
            "  Next command to improve subjective scores: `desloppify review --import findings.json`",
            "dim",
        )
    )
    print()
