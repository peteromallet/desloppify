"""Single-shot prepare/import review flows."""

from __future__ import annotations

import sys
from pathlib import Path

from desloppify import state as state_mod
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.review import import_cmd as review_import_mod
from desloppify.app.commands.review import prepare as review_prepare_mod
from desloppify.app.commands.review import runtime as review_runtime_mod
from desloppify.engine.policy.zones import FileZoneMap
from desloppify.intelligence import narrative as narrative_mod
from desloppify.intelligence import review as review_mod
from desloppify.languages import runtime as lang_runtime_mod
from desloppify.utils import colorize, log, rel

from . import output as review_output_mod


def _do_prepare(args, state, lang, _state_path, *, config: dict, holistic=True):
    """Prepare mode: holistic-only review packet in query.json."""
    return review_prepare_mod.do_prepare(
        args,
        state,
        lang,
        _state_path,
        config=config,
        holistic=bool(holistic),
        setup_lang_fn=_setup_lang,
        narrative_mod=narrative_mod,
        review_mod=review_mod,
        write_query_fn=write_query,
        colorize_fn=colorize,
        log_fn=log,
    )


def _do_import(
    import_file,
    state,
    lang,
    sp,
    holistic=True,
    config: dict | None = None,
    *,
    assessment_override: bool = False,
    assessment_note: str | None = None,
):
    """Import mode: ingest agent-produced findings."""
    if assessment_override and (
        not isinstance(assessment_note, str) or not assessment_note.strip()
    ):
        print(
            colorize(
                "  Error: --assessment-override requires --assessment-note",
                "red",
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    def _load_with_override(import_path: str) -> dict:
        return review_output_mod._load_import_findings_data(
            import_path,
            assessment_override=assessment_override,
            assessment_note=assessment_note,
        )

    def _save_with_optional_audit(state_obj: dict, state_path) -> None:
        if assessment_override:
            audit = state_obj.setdefault("assessment_import_audit", [])
            audit.append(
                {
                    "timestamp": state_mod.utc_now(),
                    "override_used": True,
                    "note": (assessment_note or "").strip(),
                    "import_file": str(import_file),
                }
            )
        state_mod.save_state(state_obj, state_path)

    return review_import_mod.do_import(
        import_file,
        state,
        lang,
        sp,
        holistic=bool(holistic),
        config=config,
        load_import_findings_data_fn=_load_with_override,
        import_holistic_findings_fn=review_mod.import_holistic_findings,
        save_state_fn=_save_with_optional_audit,
        compute_narrative_fn=narrative_mod.compute_narrative,
        print_skipped_validation_details_fn=review_output_mod._print_skipped_validation_details,
        print_assessments_summary_fn=review_output_mod._print_assessments_summary,
        print_open_review_summary_fn=review_output_mod._print_open_review_summary,
        print_review_import_scores_and_integrity_fn=review_output_mod._print_review_import_scores_and_integrity,
        write_query_fn=write_query,
        colorize_fn=colorize,
        log_fn=log,
    )


def _setup_lang(lang, path: Path, config: dict):
    """Build LangRun with zone map + dep graph and return (run, files)."""
    return review_runtime_mod.setup_lang(
        lang,
        path,
        config,
        make_lang_run_fn=lang_runtime_mod.make_lang_run,
        file_zone_map_cls=FileZoneMap,
        rel_fn=rel,
        log_fn=log,
    )
