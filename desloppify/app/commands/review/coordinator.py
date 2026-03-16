"""Session-baseline coordination helpers for external review submit guards."""

from __future__ import annotations

import json
import subprocess  # nosec
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from . import runner_packets as runner_packets_mod


def _stable_json_sha256(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _coerce_scan_count(state: Mapping[str, Any]) -> int:
    raw = state.get("scan_count", 0)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 0
    return raw


def state_sha256(state: Mapping[str, Any]) -> str:
    """Return a stable content hash for current persisted state payload."""
    return _stable_json_sha256(state)


def blind_packet_semantic_sha256(packet: Mapping[str, Any]) -> str:
    """Return stable semantic hash of blind packet content."""
    blind_packet = runner_packets_mod.build_blind_packet(dict(packet))
    return _stable_json_sha256(blind_packet)


def git_baseline(
    project_root: Path,
    *,
    subprocess_run=subprocess.run,
) -> tuple[str | None, str | None]:
    """Return (git_head, git_status_sha256) or (None, None) outside git repos."""
    command = [
        "git",
        "-C",
        str(project_root),
        "rev-parse",
        "HEAD",
    ]
    try:
        head_proc = subprocess_run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None, None
    if head_proc.returncode != 0:
        return None, None
    head = head_proc.stdout.strip() or None
    try:
        status_proc = subprocess_run(
            [
                "git",
                "-C",
                str(project_root),
                "status",
                "--porcelain",
                "--untracked-files=normal",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None, None
    status_raw = status_proc.stdout if status_proc.returncode == 0 else ""
    status_hash = _stable_json_sha256(status_raw)
    return head, status_hash


def build_review_session_baseline(
    *,
    state: Mapping[str, Any],
    packet: Mapping[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    """Capture baseline fingerprints used to reject stale external submits."""
    git_head, git_status_sha256 = git_baseline(project_root)
    return {
        "scan_count": _coerce_scan_count(state),
        "state_sha256": state_sha256(state),
        "blind_packet_semantic_sha256": blind_packet_semantic_sha256(packet),
        "git_head": git_head,
        "git_status_sha256": git_status_sha256,
    }


def evaluate_session_baseline_drift(
    *,
    expected: Mapping[str, Any],
    state: Mapping[str, Any],
    packet: Mapping[str, Any],
    project_root: Path,
    subprocess_run=subprocess.run,
) -> list[str]:
    """Return human-readable mismatch reasons when current baseline drifted."""
    reasons: list[str] = []
    reason = _scan_count_drift_reason(expected, state)
    if reason:
        reasons.append(reason)
    reason = _state_hash_drift_reason(expected, state)
    if reason:
        reasons.append(reason)
    reason = _packet_hash_drift_reason(expected, packet)
    if reason:
        reasons.append(reason)
    reasons.extend(
        _git_drift_reasons(
            expected,
            project_root=project_root,
            subprocess_run=subprocess_run,
        )
    )
    return reasons


def _scan_count_drift_reason(
    expected: Mapping[str, Any],
    state: Mapping[str, Any],
) -> str | None:
    expected_scan = expected.get("scan_count")
    if not isinstance(expected_scan, int) or isinstance(expected_scan, bool):
        return None
    observed_scan = _coerce_scan_count(state)
    if observed_scan == expected_scan:
        return None
    return f"scan_count changed (session {expected_scan}, current {observed_scan})"


def _state_hash_drift_reason(
    expected: Mapping[str, Any],
    state: Mapping[str, Any],
) -> str | None:
    expected_state = str(expected.get("state_sha256", "")).strip()
    if not expected_state:
        return None
    observed_state = state_sha256(state)
    if observed_state == expected_state:
        return None
    return "state hash changed"


def _packet_hash_drift_reason(
    expected: Mapping[str, Any],
    packet: Mapping[str, Any],
) -> str | None:
    expected_packet = str(expected.get("blind_packet_semantic_sha256", "")).strip()
    if not expected_packet:
        return None
    observed_packet = blind_packet_semantic_sha256(packet)
    if observed_packet == expected_packet:
        return None
    return "review packet content changed"


def _git_drift_reasons(
    expected: Mapping[str, Any],
    *,
    project_root: Path,
    subprocess_run,
) -> list[str]:
    expected_head = str(expected.get("git_head", "")).strip()
    expected_status = str(expected.get("git_status_sha256", "")).strip()
    if not (expected_head or expected_status):
        return []
    observed_head, observed_status = git_baseline(
        project_root,
        subprocess_run=subprocess_run,
    )
    reasons: list[str] = []
    if expected_head and observed_head and observed_head != expected_head:
        reasons.append("git HEAD changed")
    if expected_status and observed_status and observed_status != expected_status:
        reasons.append("git working tree status changed")
    return reasons


__all__ = [
    "blind_packet_semantic_sha256",
    "build_review_session_baseline",
    "evaluate_session_baseline_drift",
    "state_sha256",
]
