"""External cloud-review session helpers for review command."""

from __future__ import annotations

import json
import secrets
import shlex
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from desloppify.app.commands.helpers.query import write_query
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.exception_sets import CommandError
from desloppify.base.output.terminal import colorize
from desloppify.intelligence import review as review_mod

from .batch.orchestrator import FOLLOWUP_SCAN_TIMEOUT_SECONDS
from .coordinator import build_review_packet_payload, write_review_packet_snapshot
from .importing.cmd import do_import, do_validate_import
from .packet.build import (
    build_external_submit_next_command,
    resolve_review_packet_context,
)
from .prompt_sections import (
    build_batch_context,
    explode_to_single_dimension,
    join_non_empty_sections,
    render_dimension_prompts_block,
    render_historical_focus,
    render_mechanical_concern_signals,
    render_scan_evidence_note,
    render_scope_enums,
    render_scoring_frame,
    render_seed_files_block,
    render_task_requirements,
)
from .runner_packets import run_stamp, sha256_file
from .runner_process import FollowupScanDeps, run_followup_scan
from .runtime.setup import setup_lang_concrete
from .runtime_paths import (
    blind_packet_path as _blind_packet_path,
)
from .runtime_paths import (
    external_session_root as _external_session_root,
)
from .runtime_paths import (
    runtime_project_root as _runtime_project_root,
)

EXTERNAL_ATTEST_TEXT = (
    "I validated this review was completed without awareness of overall score and is unbiased."
)
_EXTERNAL_SUPPORTED_RUNNERS = {"claude"}



def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_seconds(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _parse_iso(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _session_id() -> str:
    return f"ext_{run_stamp()}_{secrets.token_hex(4)}"


def _session_dir(session_id: str) -> Path:
    return _external_session_root() / session_id


def _session_file(session_id: str) -> Path:
    return _session_dir(session_id) / "session.json"


def _validate_session_id(session_id: str) -> None:
    if not session_id.strip():
        raise CommandError("Error: --session-id is required.", exit_code=2)
    invalid_chars = {"/", "\\", ".."}
    if any(part in session_id for part in invalid_chars):
        raise CommandError("Error: invalid --session-id value.", exit_code=2)


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.exists():
        raise CommandError(f"Error: {label} not found: {path}")
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandError(f"Error: failed reading {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CommandError(f"Error: {label} must contain a JSON object.")
    return payload


def _session_payload(session_id: str) -> tuple[Path, dict[str, Any]]:
    _validate_session_id(session_id)
    path = _session_file(session_id)
    payload = _load_json_object(path, label="session")
    payload_id = str(payload.get("session_id", "")).strip()
    if payload_id != session_id:
        raise CommandError(
            f"Error: session id mismatch in {path} (expected {session_id}, found {payload_id or '<missing>'}).",
        )
    return path, payload


def _prepare_packet_snapshot(
    args,
    state: dict,
    lang,
    *,
    config: dict[str, Any],
) -> tuple[dict[str, Any], Path, Path]:
    """Prepare holistic review packet and persist immutable+blind snapshots."""
    context = resolve_review_packet_context(args)
    next_command = build_external_submit_next_command(context)
    try:
        packet = build_review_packet_payload(
            state=state,
            lang=lang,
            config=config,
            context=context,
            next_command=next_command,
            setup_lang_fn=setup_lang_concrete,
            prepare_holistic_review_fn=review_mod.prepare_holistic_review,
        )
    except ValueError as exc:
        raise CommandError(str(exc), exit_code=1) from exc
    write_query(packet)

    stamp = run_stamp()
    packet_path, blind_path = write_review_packet_snapshot(
        packet,
        stamp=stamp,
        blind_path_override=_blind_packet_path(),
        safe_write_text_fn=safe_write_text,
    )
    return packet, packet_path, blind_path


def _build_template_payload(packet: dict[str, Any], *, session_id: str, token: str) -> dict[str, Any]:
    dimensions = [
        dim
        for dim in packet.get("dimensions", [])
        if isinstance(dim, str) and dim.strip()
    ]
    return {
        "session": {
            "id": session_id,
            "token": token,
        },
        "assessments": {dim: 0 for dim in dimensions},
        "dimension_notes": {},
        "issues": [],
    }


def _build_claude_launch_prompt(
    *,
    session_id: str,
    token: str,
    blind_path: Path,
    template_path: Path,
    output_path: Path,
    packet: dict[str, Any],
) -> str:
    """Build a copy/paste-ready prompt for a Claude blind reviewer subagent."""
    header = (
        "# Claude Blind Reviewer Launch Prompt\n\n"
        "You are an isolated blind reviewer. Do not use prior chat context, "
        "prior score history, or target-score anchoring.\n\n"
        f"Session id: {session_id}\n"
        f"Session token: {token}\n"
        f"Blind packet: {blind_path}\n"
        f"Template JSON: {template_path}\n"
        f"Output JSON path: {output_path}\n\n"
    )

    raw_batches = packet.get("investigation_batches", [])
    if not isinstance(raw_batches, list):
        raw_batches = []
    raw_dim_prompts = packet.get("dimension_prompts")
    dim_prompts: dict[str, dict[str, object]] = (
        raw_dim_prompts if isinstance(raw_dim_prompts, dict) else {}
    )
    batches = explode_to_single_dimension(
        [b for b in raw_batches if isinstance(b, dict)],
        dimension_prompts=dim_prompts or None,
    )

    all_dims: set[str] = set()
    combined_cap = 0
    batch_sections: list[str] = []
    for i, batch in enumerate(batches):
        ctx = build_batch_context(batch, i)
        all_dims.update(ctx.dimension_set)
        combined_cap += ctx.issues_cap

        section = (
            f"--- Batch {i + 1}: {ctx.name} ---\n"
            f"Rationale: {ctx.rationale}\n"
        )
        section += render_dimension_prompts_block(ctx.dimensions, dim_prompts)
        section += render_seed_files_block(ctx)
        section += render_historical_focus(batch)
        section += render_mechanical_concern_signals(batch)
        batch_sections.append(section)

    if not combined_cap:
        combined_cap = 10

    output_schema = (
        "Output schema:\n"
        "{\n"
        '  "session": {"id": "<preserve from template>", "token": "<preserve from template>"},\n'
        '  "assessments": {"<dimension>": <0-100 with one decimal place>},\n'
        '  "dimension_notes": {\n'
        '    "<dimension>": {\n'
        '      "evidence": ["specific code observations"],\n'
        '      "impact_scope": "local|module|subsystem|codebase",\n'
        '      "fix_scope": "single_edit|multi_file_refactor|architectural_change",\n'
        '      "confidence": "high|medium|low"\n'
        "    }\n"
        "  },\n"
        '  "issues": [{\n'
        '    "dimension": "<dimension>",\n'
        '    "identifier": "short_id",\n'
        '    "summary": "one-line defect summary",\n'
        '    "related_files": ["relative/path.py"],\n'
        '    "evidence": ["specific code observation"],\n'
        '    "suggestion": "concrete fix recommendation",\n'
        '    "confidence": "high|medium|low",\n'
        '    "impact_scope": "local|module|subsystem|codebase",\n'
        '    "fix_scope": "single_edit|multi_file_refactor|architectural_change",\n'
        '    "root_cause_cluster": "optional_cluster_name"\n'
        "  }]\n"
        "}\n\n"
    )

    session_requirements = (
        "Session requirements:\n"
        f"1. Keep `session.id` exactly `{session_id}`.\n"
        f"2. Keep `session.token` exactly `{token}`.\n"
        "3. Do not include provenance metadata (CLI injects canonical provenance).\n"
    )

    return join_non_empty_sections(
        header,
        *batch_sections,
        render_scoring_frame(),
        render_scan_evidence_note(),
        render_task_requirements(issues_cap=combined_cap, dim_set=all_dims),
        render_scope_enums(),
        output_schema,
        session_requirements,
    )


def do_external_start(args, state, lang, *, config: dict[str, Any] | None = None) -> None:
    """Start an external review session with CLI-issued provenance context."""
    config = config or {}
    runner = str(getattr(args, "external_runner", "claude")).strip().lower()
    if runner not in _EXTERNAL_SUPPORTED_RUNNERS:
        raise CommandError(
            f"Error: unsupported external runner '{runner}'. Supported: claude.",
            exit_code=2,
        )
    ttl_hours = int(getattr(args, "session_ttl_hours", 24) or 0)
    if ttl_hours <= 0:
        raise CommandError("Error: --session-ttl-hours must be > 0.", exit_code=2)

    packet, packet_path, blind_path = _prepare_packet_snapshot(
        args,
        state,
        lang,
        config=config,
    )
    packet_hash = sha256_file(blind_path)
    if not isinstance(packet_hash, str):
        raise CommandError(f"Error: failed to hash blind packet: {blind_path}")

    now = _utc_now()
    expires = now + timedelta(hours=ttl_hours)
    session_id = _session_id()
    token = secrets.token_hex(16)
    session_dir = _session_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    template_payload = _build_template_payload(packet, session_id=session_id, token=token)
    template_path = session_dir / "review_result.template.json"
    instructions_path = session_dir / "reviewer_instructions.md"
    launch_prompt_path = session_dir / "claude_launch_prompt.md"
    output_path = session_dir / "review_result.json"
    session_path = _session_file(session_id)

    session_payload = {
        "session_id": session_id,
        "status": "open",
        "runner": runner,
        "created_at": _iso_seconds(now),
        "expires_at": _iso_seconds(expires),
        "ttl_hours": ttl_hours,
        "token": token,
        "attest": EXTERNAL_ATTEST_TEXT,
        "packet_path": str(packet_path),
        "blind_packet_path": str(blind_path),
        "packet_sha256": packet_hash,
        "template_path": str(template_path),
        "launch_prompt_path": str(launch_prompt_path),
        "instructions_path": str(instructions_path),
        "expected_output_path": str(output_path),
    }
    safe_write_text(session_path, json.dumps(session_payload, indent=2) + "\n")
    safe_write_text(template_path, json.dumps(template_payload, indent=2) + "\n")
    safe_write_text(
        launch_prompt_path,
        _build_claude_launch_prompt(
            session_id=session_id,
            token=token,
            blind_path=blind_path,
            template_path=template_path,
            output_path=output_path,
            packet=packet,
        )
        + "\n",
    )

    instructions = "\n".join(
        [
            "# External Blind Review Session",
            "",
            f"Session id: {session_id}",
            f"Session token: {token}",
            f"Blind packet: {blind_path}",
            f"Template output: {template_path}",
            f"Claude launch prompt: {launch_prompt_path}",
            f"Expected reviewer output: {output_path}",
            "",
            "Happy path:",
            "1. Open the Claude launch prompt file and paste it into a context-isolated subagent task.",
            "2. Reviewer writes JSON output to the expected reviewer output path.",
            "3. Submit with the printed --external-submit command.",
            "",
            "Reviewer output requirements:",
            "1. Return JSON with top-level keys: session, assessments, issues.",
            f"2. session.id must be `{session_id}`.",
            f"3. session.token must be `{token}`.",
            "4. Include issues with required schema fields (dimension/identifier/summary/related_files/evidence/suggestion/confidence).",
            "5. Use the blind packet only (no score targets or prior context).",
        ]
    )
    safe_write_text(instructions_path, instructions + "\n")

    submit_cmd = (
        "desloppify review --external-submit "
        f"--session-id {session_id} --import {output_path}"
    )
    submit_with_scan_cmd = f"{submit_cmd} --scan-after-import"
    print(colorize("\n  External review session started.", "bold"))
    print(colorize(f"  Runner: {runner}", "dim"))
    print(colorize(f"  Session id: {session_id}", "dim"))
    print(colorize(f"  Session expires: {session_payload['expires_at']}", "dim"))
    print(colorize(f"  Immutable packet: {packet_path}", "dim"))
    print(colorize(f"  Blind packet: {blind_path}", "dim"))
    print(colorize(f"  Session file: {session_path}", "dim"))
    print(colorize(f"  Reviewer template: {template_path}", "dim"))
    print(colorize(f"  Claude launch prompt: {launch_prompt_path}", "dim"))
    print(colorize(f"  Reviewer instructions: {instructions_path}", "dim"))
    print(colorize("\n  Next steps:", "yellow"))
    print(
        colorize(
            f"  1. Open launch prompt: `cat {shlex.quote(str(launch_prompt_path))}`",
            "dim",
        )
    )
    print(colorize(f"  2. Reviewer output target: `{output_path}`", "dim"))
    print(colorize(f"  3. Submit results: `{submit_cmd}`", "dim"))
    print(colorize(f"  4. Optional auto-rescan: `{submit_with_scan_cmd}`", "dim"))


def _canonical_external_payload(
    raw_payload: dict[str, Any],
    *,
    session: dict[str, Any],
) -> dict[str, Any]:
    """Return import payload with canonical provenance and required session token."""
    session_meta = raw_payload.get("session")
    if not isinstance(session_meta, dict):
        raise CommandError(
            "Error: external reviewer payload must include top-level `session` object."
            ' Expected: {"session":{"id":"...","token":"..."},"assessments":{...},"issues":[...]}',
        )

    payload_id = str(session_meta.get("id", "")).strip()
    payload_token = str(session_meta.get("token", "")).strip()
    expected_id = str(session.get("session_id", "")).strip()
    expected_token = str(session.get("token", "")).strip()
    if payload_id != expected_id or payload_token != expected_token:
        raise CommandError(
            "Error: session id/token mismatch in external reviewer payload."
            " Regenerate output using the session template/instructions.",
        )

    payload = {
        key: value
        for key, value in raw_payload.items()
        if key not in {"session", "provenance"}
    }
    payload["provenance"] = {
        "kind": "blind_review_batch_import",
        "blind": True,
        "runner": str(session.get("runner", "claude")),
        "session_id": str(session.get("session_id", "")),
        "created_at": _iso_seconds(_utc_now()),
        "packet_path": str(session.get("blind_packet_path", "")),
        "packet_sha256": str(session.get("packet_sha256", "")),
    }
    return payload


def _ensure_session_open(session: dict[str, Any]) -> None:
    status = str(session.get("status", "open")).strip().lower()
    if status == "open":
        return
    raise CommandError(
        f"Error: session is not open (status={status or 'unknown'}). Start a new session with --external-start.",
    )


def _ensure_session_not_expired(session: dict[str, Any]) -> None:
    expires_at = _parse_iso(session.get("expires_at"))
    if expires_at is None:
        raise CommandError(
            "Error: session metadata is missing/invalid expires_at.",
        )
    now = _utc_now()
    if now <= expires_at:
        return
    raise CommandError(
        f"Error: session expired at {session.get('expires_at')}. Start a new session with --external-start.",
    )


def do_external_submit(
    *,
    import_file: str,
    session_id: str,
    state: dict,
    lang,
    state_file,
    config: dict[str, Any] | None = None,
    allow_partial: bool = False,
    scan_after_import: bool = False,
    scan_path: str = ".",
    dry_run: bool = False,
) -> None:
    """Submit external reviewer output via session, adding canonical provenance."""
    config = config or {}
    session_path, session = _session_payload(session_id)
    _ensure_session_open(session)
    _ensure_session_not_expired(session)

    if str(session.get("runner", "")).strip().lower() not in _EXTERNAL_SUPPORTED_RUNNERS:
        raise CommandError(
            "Error: only Claude external sessions currently support durable score submit.",
        )

    issues_path = Path(import_file)
    raw_payload = _load_json_object(issues_path, label="external issues")
    canonical_payload = _canonical_external_payload(raw_payload, session=session)

    stamp = run_stamp()
    session_dir = session_path.parent
    canonical_path = session_dir / f"canonical_import_{stamp}.json"
    safe_write_text(canonical_path, json.dumps(canonical_payload, indent=2) + "\n")

    if dry_run:
        do_validate_import(
            str(canonical_path),
            lang,
            allow_partial=allow_partial,
            attested_external=True,
            manual_attest=str(session.get("attest", EXTERNAL_ATTEST_TEXT)),
        )
        return

    do_import(
        str(canonical_path),
        state,
        lang,
        state_file,
        config=config,
        allow_partial=allow_partial,
        attested_external=True,
        manual_attest=str(session.get("attest", EXTERNAL_ATTEST_TEXT)),
    )

    submitted_at = _iso_seconds(_utc_now())
    session["status"] = "submitted"
    session["submitted_at"] = submitted_at
    session["submitted_input_file"] = str(issues_path)
    session["submitted_canonical_file"] = str(canonical_path)
    safe_write_text(session_path, json.dumps(session, indent=2) + "\n")

    if scan_after_import:
        code = run_followup_scan(
            lang_name=lang.name,
            scan_path=scan_path,
            deps=FollowupScanDeps(
                project_root=_runtime_project_root(),
                timeout_seconds=FOLLOWUP_SCAN_TIMEOUT_SECONDS,
                python_executable=sys.executable,
                subprocess_run=subprocess.run,
                timeout_error=subprocess.TimeoutExpired,
                colorize_fn=colorize,
            ),
        )
        if code != 0:
            raise CommandError(f"External review exited with code {code}", exit_code=code)


__all__ = ["do_external_start", "do_external_submit", "EXTERNAL_ATTEST_TEXT"]
