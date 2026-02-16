"""review command: prepare or import subjective code review findings."""

import json
import logging
import sys
from pathlib import Path

from ..command_vocab import ISSUES
from ..utils import colorize

LOGGER = logging.getLogger(__name__)


def cmd_review(args) -> None:
    """Prepare or import subjective code review findings."""
    from ..state import load_state
    from ._helpers import state_path, resolve_lang

    sp = state_path(args)
    state = load_state(sp)
    lang = resolve_lang(args)

    if not lang:
        print(colorize("  Error: could not detect language. Use --lang.", "red"), file=sys.stderr)
        sys.exit(1)

    import_file = getattr(args, "import_file", None)
    holistic = getattr(args, "holistic", False)
    assessment_override = getattr(args, "assessment_override", False)
    assessment_note = getattr(args, "assessment_note", None)
    cfg = getattr(args, "_config", None) or {}
    from ..review import build_dimension_policy
    policy = build_dimension_policy(
        state=state,
        config=cfg,
        allow_custom_dimensions=bool(getattr(args, "allow_custom_dimensions", False)),
    )

    if import_file:
        _do_import(
            import_file,
            state,
            lang,
            sp,
            holistic=holistic,
            assessment_override=assessment_override,
            assessment_note=assessment_note,
            policy=policy,
            config=cfg,
        )
    else:
        _do_prepare(
            args,
            state,
            lang,
            sp,
            holistic=holistic,
            policy=policy,
        )


def _do_prepare(args, state, lang, sp, holistic=False, allow_custom_dimensions=False, policy=None):
    """Prepare mode: compute what needs review, output to query.json."""
    from ._helpers import _write_query, show_narrative_plan, show_narrative_reminders
    from ..narrative import compute_narrative
    from ..review import (
        CUSTOM_DIMENSION_PREFIX,
        build_dimension_policy,
        normalize_dimension_inputs,
    )

    path = Path(args.path)
    effective_policy = policy or build_dimension_policy(
        state=state,
        config=getattr(args, "_config", None),
        allow_custom_dimensions=allow_custom_dimensions,
    )
    dims_str = getattr(args, "dimensions", None)
    raw_dims = [d.strip() for d in dims_str.split(",")] if dims_str else None
    dimensions, invalid_dims = normalize_dimension_inputs(
        raw_dims,
        holistic=holistic,
        policy=effective_policy,
    )
    if invalid_dims:
        mode_label = "holistic" if holistic else "per-file"
        print(
            colorize(
                f"  Error: invalid {mode_label} dimension(s): {', '.join(invalid_dims)}",
                "red",
            ),
            file=sys.stderr,
        )
        print(
            colorize(
                f"  Use known dimensions, or enable explicit custom dimensions with "
                f"`--allow-custom-dimensions` and names prefixed `{CUSTOM_DIMENSION_PREFIX}`.",
                "yellow",
            ),
            file=sys.stderr,
        )
        sys.exit(2)
    dimensions = dimensions or None

    # Build zone map and dep graph (required for file selection and context)
    # _setup_lang returns the file list so we can pass it through (avoids re-walking)
    found_files = _setup_lang(lang, path, args._config)

    lang_name = lang.name
    narrative = compute_narrative(
        state,
        lang=lang_name,
        command="review",
        config=getattr(args, "_config", None),
    )

    if holistic:
        from ..review import prepare_holistic_review
        data = prepare_holistic_review(
            path, lang, state,
            dimensions=dimensions,
            policy=effective_policy,
            files=found_files or None,
        )
        data["narrative"] = narrative
        _write_query(data)
        total = data.get("total_files", 0)
        batches = data.get("investigation_batches", [])
        print(colorize(f"\n  Holistic review prepared: {total} files in codebase", "bold"))
        if batches:
            print(colorize("\n  Investigation batches (independent — can run in parallel):", "bold"))
            for i, batch in enumerate(batches, 1):
                n_files = len(batch["files_to_read"])
                print(colorize(f"    {i}. {batch['name']} ({n_files} files) — {batch['why']}", "dim"))
        print(colorize("\n  Workflow:", "bold"))
        for step_i, step in enumerate(data.get("workflow", []), 1):
            print(colorize(f"    {step_i}. {step}", "dim"))
        print(colorize("\n  \u2192 query.json updated. "
                "Review codebase, then: desloppify review --import findings.json --holistic", "cyan"))
    else:
        from ..review import prepare_review
        max_files = getattr(args, "max_files", 50)
        max_age_cli = getattr(args, "max_age", None)
        max_age = max_age_cli if max_age_cli is not None else args._config.get("review_max_age_days", 30)
        force_refresh = getattr(args, "refresh", False)
        raw_config_dims = args._config.get("review_dimensions") or None
        config_dims, invalid_config_dims = normalize_dimension_inputs(
            list(raw_config_dims) if isinstance(raw_config_dims, list) else None,
            holistic=False,
            policy=effective_policy,
        )
        # Filter empty lists from config
        if config_dims is not None and not config_dims:
            config_dims = None
        if invalid_config_dims:
            print(
                colorize(
                    f"  Warning: ignored invalid config review_dimensions: "
                    f"{', '.join(invalid_config_dims)}",
                    "yellow",
                )
            )
        data = prepare_review(
            path, lang, state,
            max_files=max_files,
            max_age_days=max_age,
            force_refresh=force_refresh,
            dimensions=dimensions,
            config_dimensions=config_dims,
            policy=effective_policy,
            files=found_files or None,
        )
        data["narrative"] = narrative
        _write_query(data)
        print(colorize(f"\n  Review prepared: {data['total_candidates']} files to review", "bold"))
        print(colorize(f"  Cache: {data['cache_status']['fresh']} fresh, "
                f"{data['cache_status']['stale']} stale, "
                f"{data['cache_status']['new']} new", "dim"))
        print(colorize(f"  Dimensions: {', '.join(data['dimensions'])}", "dim"))
        print(colorize("\n  \u2192 query.json updated. "
                "Review files, then: desloppify review --import findings.json", "cyan"))
    show_narrative_plan(narrative, max_risks=1)
    show_narrative_reminders(
        narrative,
        limit=2,
        skip_types={"report_scores", "review_findings_pending"},
    )


def _do_import(
    import_file,
    state,
    lang,
    sp,
    holistic=False,
    assessment_override=False,
    assessment_note=None,
    allow_custom_dimensions=False,
    policy=None,
    config: dict | None = None,
):
    """Import mode: ingest agent-produced findings."""
    from ..state import save_state, utc_now
    from ._helpers import _write_query, show_narrative_plan, show_narrative_reminders
    from ..narrative import compute_narrative
    from ..review import build_dimension_policy

    findings_path = Path(import_file)
    if not findings_path.exists():
        print(colorize(f"  Error: file not found: {import_file}", "red"), file=sys.stderr)
        sys.exit(1)

    try:
        findings_data = json.loads(findings_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(colorize(f"  Error reading findings: {e}", "red"), file=sys.stderr)
        sys.exit(1)

    # Accept both legacy (list) and new format (dict with assessments + findings)
    if isinstance(findings_data, dict):
        if "findings" not in findings_data:
            print(colorize("  Error: findings object must contain a 'findings' key", "red"), file=sys.stderr)
            sys.exit(1)
    elif isinstance(findings_data, list):
        # Legacy format: bare array of findings
        findings_data = {"findings": findings_data}
    else:
        print(colorize("  Error: findings file must contain a JSON array or object", "red"), file=sys.stderr)
        sys.exit(1)

    effective_policy = policy or build_dimension_policy(
        state=state,
        config=config,
        allow_custom_dimensions=allow_custom_dimensions,
    )

    from ..review.import_findings import (
        validate_assessment_import_integrity,
        AssessmentImportIntegrityError,
    )
    try:
        integrity = validate_assessment_import_integrity(
            state,
            findings_data,
            mode="holistic" if holistic else "per_file",
            allow_override=assessment_override,
            override_note=assessment_note,
            policy=effective_policy,
        )
    except AssessmentImportIntegrityError as e:
        print(colorize(f"  Error: {e}", "red"), file=sys.stderr)
        sys.exit(1)

    if integrity and integrity.get("checked"):
        audit_entry = {
            "at": utc_now(),
            "mode": integrity.get("mode", "per_file"),
            "changed_dimensions": integrity.get("changed_dimensions", []),
            "aggregate_delta": integrity.get("aggregate_delta", 0.0),
            "max_dimension_delta": integrity.get("max_dimension_delta", 0.0),
            "finding_count": integrity.get("finding_count", 0),
            "override_used": integrity.get("override_used", False),
            "override_note": integrity.get("override_note", ""),
        }
        audit = state.setdefault("assessment_import_audit", [])
        audit.append(audit_entry)
        if len(audit) > 200:
            del audit[:-200]

    if holistic:
        from ..review import import_holistic_findings
        diff = import_holistic_findings(
            findings_data,
            state,
            lang.name,
            policy=effective_policy,
        )
        label = "Holistic review"
    else:
        from ..review import import_review_findings
        diff = import_review_findings(
            findings_data,
            state,
            lang.name,
            policy=effective_policy,
        )
        label = "Review"

    save_state(state, sp)

    lang_name = lang.name
    narrative = compute_narrative(
        state,
        lang=lang_name,
        command="review",
        config=config,
    )
    _write_query({"command": "review", "action": "import", "mode": "holistic" if holistic else "per_file",
                  "diff": diff, "narrative": narrative})

    print(colorize(f"\n  {label} imported:", "bold"))
    print(colorize(f"  +{diff['new']} new findings, "
            f"{diff['auto_resolved']} resolved, "
            f"{diff['reopened']} reopened", "dim"))

    # Warn about skipped findings so agent can fix their output
    n_skipped = diff.get("skipped", 0)
    if n_skipped > 0:
        print(colorize(f"\n  \u26a0 {n_skipped} finding(s) skipped (validation errors):", "yellow"))
        for detail in diff.get("skipped_details", []):
            reasons = detail['missing']
            # Separate actual missing fields from validation errors
            missing_fields = [r for r in reasons if not r.startswith("invalid ")]
            validation_errors = [r for r in reasons if r.startswith("invalid ")]
            parts = []
            if missing_fields:
                parts.append(f"missing {', '.join(missing_fields)}")
            parts.extend(validation_errors)
            print(colorize(f"    #{detail['index']} ({detail['identifier']}): "
                    f"{'; '.join(parts)}", "yellow"))
    skipped_assessment_dims = diff.get("assessment_skipped_dimensions", [])
    if skipped_assessment_dims:
        print(
            colorize(
                "\n  \u26a0 Assessment dimensions ignored: "
                + ", ".join(skipped_assessment_dims),
                "yellow",
            )
        )

    if integrity and integrity.get("override_used"):
        print(colorize(
            f"\n  \u26a0 Assessment override applied "
            f"(aggregate Δ={integrity['aggregate_delta']}, "
            f"max dimension Δ={integrity['max_dimension_delta']}).",
            "yellow",
        ))

    # Show assessment summary if any were stored
    assessments = state.get("subjective_assessments") or state.get("review_assessments") or {}
    if assessments:
        parts = [f"{k.replace('_', ' ')} {v['score']}" for k, v in sorted(assessments.items())]
        print(colorize(f"\n  Assessments: {', '.join(parts)}", "bold"))

    open_review = [f for f in state["findings"].values()
                   if f["status"] == "open" and f.get("detector") == "review"]
    if open_review:
        print(colorize(f"\n  {len(open_review)} review finding{'s' if len(open_review) != 1 else ''} open total", "bold"))
        print(colorize(f"  Run `{ISSUES}` to see the work queue", "dim"))

    from ..state import get_overall_score, get_objective_score, get_strict_score
    overall = get_overall_score(state)
    objective = get_objective_score(state)
    strict = get_strict_score(state)
    if overall is not None and objective is not None and strict is not None:
        print(colorize(
            f"\n  Current scores: overall {overall:.1f}/100 · "
            f"objective {objective:.1f}/100 · strict {strict:.1f}/100",
            "dim",
        ))
    show_narrative_plan(narrative, max_risks=1)
    show_narrative_reminders(
        narrative,
        limit=2,
        skip_types={"report_scores", "review_findings_pending"},
    )


def _setup_lang(lang, path: Path, config: dict) -> list[str]:
    """Build zone map and dep graph for the language config.

    Returns the file list from file_finder (so callers can reuse it).
    """
    files: list[str] = []

    # Build zone map
    if lang.zone_rules and lang.file_finder:
        from ..zones import FileZoneMap
        from ..utils import rel
        files = lang.file_finder(path)
        zone_overrides = config.get("zone_overrides") or None
        lang._zone_map = FileZoneMap(files, lang.zone_rules, rel_fn=rel,
                                      overrides=zone_overrides)

    # Build dep graph
    if lang.build_dep_graph and lang._dep_graph is None:
        try:
            lang._dep_graph = lang.build_dep_graph(path)
        except (OSError, UnicodeDecodeError, ValueError, SyntaxError, TypeError, RuntimeError) as exc:
            LOGGER.debug("Dependency graph unavailable for review context", exc_info=exc)

    return files
