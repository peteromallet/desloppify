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
from desloppify.app.commands.review import runner_helpers as runner_helpers_mod
from desloppify.app.commands.review.runtime import setup_lang_concrete
from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.file_discovery import safe_write_text
from desloppify.intelligence import narrative as narrative_mod
from desloppify.intelligence import review as review_mod
from desloppify.utils import colorize

from .import_cmd import do_import, do_validate_import

REVIEW_PACKET_DIR = PROJECT_ROOT / ".desloppify" / "review_packets"
EXTERNAL_SESSION_ROOT = PROJECT_ROOT / ".desloppify" / "external_review_sessions"
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


def _split_dimensions(raw: object) -> list[str] | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    values = [value.strip() for value in raw.split(",")]
    cleaned = [value for value in values if value]
    return cleaned or None


def _coerce_positive_int(value: object, *, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int | float | str):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _session_id() -> str:
    return f"ext_{runner_helpers_mod.run_stamp()}_{secrets.token_hex(4)}"


def _session_dir(session_id: str) -> Path:
    return EXTERNAL_SESSION_ROOT / session_id


def _session_file(session_id: str) -> Path:
    return _session_dir(session_id) / "session.json"


def _validate_session_id_or_exit(session_id: str) -> None:
    if not session_id.strip():
        print(colorize("  Error: --session-id is required.", "red"), file=sys.stderr)
        sys.exit(2)
    invalid_chars = {"/", "\\", ".."}
    if any(part in session_id for part in invalid_chars):
        print(colorize("  Error: invalid --session-id value.", "red"), file=sys.stderr)
        sys.exit(2)


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.exists():
        print(colorize(f"  Error: {label} not found: {path}", "red"), file=sys.stderr)
        sys.exit(1)
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(colorize(f"  Error: failed reading {label}: {exc}", "red"), file=sys.stderr)
        sys.exit(1)
    if not isinstance(payload, dict):
        print(
            colorize(f"  Error: {label} must contain a JSON object.", "red"),
            file=sys.stderr,
        )
        sys.exit(1)
    return payload


def _session_payload_or_exit(session_id: str) -> tuple[Path, dict[str, Any]]:
    _validate_session_id_or_exit(session_id)
    path = _session_file(session_id)
    payload = _load_json_object(path, label="session")
    payload_id = str(payload.get("session_id", "")).strip()
    if payload_id != session_id:
        print(
            colorize(
                f"  Error: session id mismatch in {path} (expected {session_id}, found {payload_id or '<missing>'}).",
                "red",
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    return path, payload


def _prepare_packet_snapshot(
    args,
    state: dict,
    lang,
    *,
    config: dict[str, Any],
) -> tuple[dict[str, Any], Path, Path]:
    """Prepare holistic review packet and persist immutable+blind snapshots."""
    path = Path(getattr(args, "path", ".") or ".")
    dimensions = _split_dimensions(getattr(args, "dimensions", None))
    retrospective = bool(getattr(args, "retrospective", False))
    retrospective_max_issues = _coerce_positive_int(
        getattr(args, "retrospective_max_issues", None),
        default=30,
    )
    retrospective_max_batch_items = _coerce_positive_int(
        getattr(args, "retrospective_max_batch_items", None),
        default=20,
    )
    lang_run, found_files = setup_lang_concrete(lang, path, config)
    narrative = narrative_mod.compute_narrative(
        state,
        context=narrative_mod.NarrativeContext(lang=lang_run.name, command="review"),
    )
    packet = review_mod.prepare_holistic_review(
        path,
        lang_run,
        state,
        options=review_mod.HolisticReviewPrepareOptions(
            dimensions=dimensions,
            files=found_files or None,
            include_issue_history=retrospective,
            issue_history_max_issues=retrospective_max_issues,
            issue_history_max_batch_items=retrospective_max_batch_items,
        ),
    )
    packet["narrative"] = narrative
    next_command = "desloppify review --external-submit --session-id <id> --import <file>"
    if retrospective:
        next_command += (
            " --retrospective"
            f" --retrospective-max-issues {retrospective_max_issues}"
            f" --retrospective-max-batch-items {retrospective_max_batch_items}"
        )
    packet["next_command"] = next_command
    write_query(packet)

    stamp = runner_helpers_mod.run_stamp()
    blind_packet_path = PROJECT_ROOT / ".desloppify" / "review_packet_blind.json"
    packet_path, blind_path = runner_helpers_mod.write_packet_snapshot(
        packet,
        stamp=stamp,
        review_packet_dir=REVIEW_PACKET_DIR,
        blind_path=blind_packet_path,
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
        "findings": [],
    }


def _build_claude_launch_prompt(
    *,
    session_id: str,
    token: str,
    blind_path: Path,
    template_path: Path,
    output_path: Path,
) -> str:
    """Build a copy/paste-ready prompt for a Claude blind reviewer subagent."""
    return "\n".join(
        [
            "# Claude Blind Reviewer Launch Prompt",
            "",
            "You are an isolated blind reviewer. Do not use prior chat context, prior score history, or target-score anchoring.",
            "",
            f"Blind packet: {blind_path}",
            f"Template JSON: {template_path}",
            f"Output JSON path: {output_path}",
            "",
            "Requirements:",
            "1. Read ONLY the blind packet and repository code.",
            "2. Start from the template JSON so `session.id` and `session.token` are preserved.",
            f"3. Keep `session.id` exactly `{session_id}`.",
            f"4. Keep `session.token` exactly `{token}`.",
            "5. Output must be valid JSON with top-level keys: session, assessments, findings.",
            "6. Every finding must include: dimension, identifier, summary, related_files, evidence, suggestion, confidence.",
            "7. Do not include provenance metadata (CLI injects canonical provenance).",
            "8. Return JSON only (no markdown fences).",
        ]
    )


def do_external_start(args, state, lang, *, config: dict[str, Any] | None = None) -> None:
    """Start an external review session with CLI-issued provenance context."""
    config = config or {}
    runner = str(getattr(args, "external_runner", "claude")).strip().lower()
    if runner not in _EXTERNAL_SUPPORTED_RUNNERS:
        print(
            colorize(
                f"  Error: unsupported external runner '{runner}'. Supported: claude.",
                "red",
            ),
            file=sys.stderr,
        )
        sys.exit(2)
    ttl_hours = int(getattr(args, "session_ttl_hours", 24) or 0)
    if ttl_hours <= 0:
        print(colorize("  Error: --session-ttl-hours must be > 0.", "red"), file=sys.stderr)
        sys.exit(2)

    packet, packet_path, blind_path = _prepare_packet_snapshot(
        args,
        state,
        lang,
        config=config,
    )
    packet_hash = runner_helpers_mod.sha256_file(blind_path)
    if not isinstance(packet_hash, str):
        print(
            colorize(f"  Error: failed to hash blind packet: {blind_path}", "red"),
            file=sys.stderr,
        )
        sys.exit(1)

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
            "1. Return JSON with top-level keys: session, assessments, findings.",
            f"2. session.id must be `{session_id}`.",
            f"3. session.token must be `{token}`.",
            "4. Include findings with required schema fields (dimension/identifier/summary/related_files/evidence/suggestion/confidence).",
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
        print(
            colorize(
                "  Error: external reviewer payload must include top-level `session` object.",
                "red",
            ),
            file=sys.stderr,
        )
        print(
            colorize(
                "  Expected: {\"session\":{\"id\":\"...\",\"token\":\"...\"},\"assessments\":{...},\"findings\":[...]}",
                "dim",
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    payload_id = str(session_meta.get("id", "")).strip()
    payload_token = str(session_meta.get("token", "")).strip()
    expected_id = str(session.get("session_id", "")).strip()
    expected_token = str(session.get("token", "")).strip()
    if payload_id != expected_id or payload_token != expected_token:
        print(
            colorize(
                "  Error: session id/token mismatch in external reviewer payload.",
                "red",
            ),
            file=sys.stderr,
        )
        print(
            colorize("  Regenerate output using the session template/instructions.", "yellow"),
            file=sys.stderr,
        )
        sys.exit(1)

    payload = dict(raw_payload)
    payload.pop("session", None)
    payload.pop("provenance", None)
    payload["provenance"] = {
        "kind": "blind_review_batch_import",
        "blind": True,
        "runner": str(session.get("runner", "claude")),
        "run_stamp": str(session.get("session_id", "")),
        "created_at": _iso_seconds(_utc_now()),
        "packet_path": str(session.get("blind_packet_path", "")),
        "packet_sha256": str(session.get("packet_sha256", "")),
        "external_session_id": expected_id,
    }
    return payload


def _ensure_session_open_or_exit(session: dict[str, Any]) -> None:
    status = str(session.get("status", "open")).strip().lower()
    if status == "open":
        return
    print(
        colorize(
            f"  Error: session is not open (status={status or 'unknown'}). Start a new session with --external-start.",
            "red",
        ),
        file=sys.stderr,
    )
    sys.exit(1)


def _ensure_session_not_expired_or_exit(session: dict[str, Any]) -> None:
    expires_at = _parse_iso(session.get("expires_at"))
    if expires_at is None:
        print(
            colorize(
                "  Error: session metadata is missing/invalid expires_at.",
                "red",
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    now = _utc_now()
    if now <= expires_at:
        return
    print(
        colorize(
            f"  Error: session expired at {session.get('expires_at')}. Start a new session with --external-start.",
            "red",
        ),
        file=sys.stderr,
    )
    sys.exit(1)


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
    session_path, session = _session_payload_or_exit(session_id)
    _ensure_session_open_or_exit(session)
    _ensure_session_not_expired_or_exit(session)

    if str(session.get("runner", "")).strip().lower() not in _EXTERNAL_SUPPORTED_RUNNERS:
        print(
            colorize(
                "  Error: only Claude external sessions currently support durable score submit.",
                "red",
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    findings_path = Path(import_file)
    raw_payload = _load_json_object(findings_path, label="external findings")
    canonical_payload = _canonical_external_payload(raw_payload, session=session)

    stamp = runner_helpers_mod.run_stamp()
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
    session["submitted_input_file"] = str(findings_path)
    session["submitted_canonical_file"] = str(canonical_path)
    safe_write_text(session_path, json.dumps(session, indent=2) + "\n")

    if scan_after_import:
        from .batch import FOLLOWUP_SCAN_TIMEOUT_SECONDS

        code = runner_helpers_mod.run_followup_scan(
            lang_name=lang.name,
            scan_path=scan_path,
            deps=runner_helpers_mod.FollowupScanDeps(
                project_root=PROJECT_ROOT,
                timeout_seconds=FOLLOWUP_SCAN_TIMEOUT_SECONDS,
                python_executable=sys.executable,
                subprocess_run=subprocess.run,
                timeout_error=subprocess.TimeoutExpired,
                colorize_fn=colorize,
            ),
        )
        if code != 0:
            raise SystemExit(code)


__all__ = ["do_external_start", "do_external_submit", "EXTERNAL_ATTEST_TEXT"]
