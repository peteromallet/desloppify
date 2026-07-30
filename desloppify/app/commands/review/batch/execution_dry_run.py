"""Dry-run output writer for batch execution."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .scope import is_prompt_only_runner


def maybe_handle_dry_run(
    *,
    args,
    stamp: str,
    selected_indexes: list[int],
    run_dir: Path,
    logs_dir: Path,
    immutable_packet_path: Path,
    prompt_packet_path: Path,
    prompt_files: dict,
    output_files: dict,
    safe_write_text_fn,
    colorize_fn,
    append_run_log,
) -> bool:
    """Write dry-run artifacts and guidance. Returns True when handled."""
    runner = str(getattr(args, "runner", "") or "").strip().lower()
    prompt_only = is_prompt_only_runner(runner)
    if not getattr(args, "dry_run", False) and not prompt_only:
        return False

    # Record the runner that will execute these prompts rather than the literal
    # "dry-run".  The import trust gate matches provenance.runner against the
    # supported-runner set, so a placeholder here makes the resulting artifact
    # permanently unimportable for scores -- which silently broke the
    # prompt-only (Claude subagent) path entirely.  `dry_run` stays in the
    # summary so the artifact still records that desloppify skipped execution;
    # assessments from this path are never auto-applied (that requires an
    # in-process run), so they still demand --attested-external at import.
    dry_summary: dict[str, object] = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "run_stamp": stamp,
        "runner": runner or "dry-run",
        "dry_run": True,
        "parallel": False,
        "selected_batches": [idx + 1 for idx in selected_indexes],
        "successful_batches": [idx + 1 for idx in selected_indexes],
        "failed_batches": [],
        "immutable_packet": str(immutable_packet_path),
        "blind_packet": str(prompt_packet_path),
        "run_dir": str(run_dir),
        "logs_dir": str(logs_dir),
        "batches": {
            str(idx + 1): {
                "status": "pending",
                "prompt_path": str(prompt_files[idx]),
                "result_path": str(output_files[idx]),
            }
            for idx in selected_indexes
        },
    }
    dry_summary_path = run_dir / "run_summary.json"
    safe_write_text_fn(dry_summary_path, json.dumps(dry_summary, indent=2) + "\n")

    n = len(selected_indexes)
    label = (
        f"  Prompt-only runner '{runner}': {n} prompt(s) generated, "
        "execution left to the calling harness."
        if prompt_only
        else f"  Dry run: {n} prompt(s) generated, runner execution skipped."
    )
    print(colorize_fn(label, "yellow"))
    print(colorize_fn(f"  Run directory: {run_dir}", "dim"))
    print(colorize_fn(f"  Immutable packet: {immutable_packet_path}", "dim"))
    print(colorize_fn(f"  Blind packet: {prompt_packet_path}", "dim"))
    print(colorize_fn(f"  Prompts: {run_dir / 'prompts'}", "dim"))
    print(colorize_fn(f"  Results: {run_dir / 'results'}  (write subagent output here)", "dim"))
    print()
    print(
        colorize_fn(
            f"  Next: launch {n} subagent(s), one per prompt file. "
            "Each writes JSON output to the matching results/ file.",
            "bold",
        )
    )
    import_cmd = f"  Then: desloppify review --import-run {run_dir} --scan-after-import"
    if prompt_only:
        # Assessments from a prompt-only run are never auto-applied; without the
        # attestation the import silently downgrades to issues-only.
        import_cmd += (
            ' --attested-external --attest "I validated this review was '
            'completed without awareness of overall score and is unbiased."'
        )
    print(colorize_fn(import_cmd, "bold"))
    append_run_log(f"run-finished {'prompt-only' if prompt_only else 'dry-run'}")
    return True


__all__ = ["maybe_handle_dry_run"]
