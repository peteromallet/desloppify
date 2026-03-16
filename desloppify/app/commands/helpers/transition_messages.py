"""Emit user-configured messages at lifecycle phase transitions."""

from __future__ import annotations

import json as _json
import logging
import os as _os
import urllib.error as _urlerr
import urllib.request as _urlreq

from desloppify.base.config import load_config
from desloppify.base.output.user_message import print_user_message
from desloppify.engine._plan.refresh_lifecycle import (
    COARSE_PHASE_MAP,
    LIFECYCLE_PHASE_EXECUTE,
    LIFECYCLE_PHASE_SCAN,
)

logger = logging.getLogger(__name__)

# Phases that are NOT postflight — everything else counts as postflight.
_NON_POSTFLIGHT = frozenset({LIFECYCLE_PHASE_EXECUTE, LIFECYCLE_PHASE_SCAN})

_HERMES_PORT_FILE = _os.path.expanduser("~/.hermes/control_api.port")


def _hermes_available() -> bool:
    """Check if Hermes integration is enabled in config."""
    try:
        config = load_config()
    except (OSError, ValueError):
        return False
    return bool(config.get("hermes_enabled", False))


def _hermes_port() -> int:
    try:
        with open(_HERMES_PORT_FILE) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 47823


def _hermes_get(path: str) -> dict:
    """GET a Hermes control API endpoint. Stdlib-only, no deps."""
    url = f"http://127.0.0.1:{_hermes_port()}{path}"
    req = _urlreq.Request(url, method="GET",
                          headers={"X-Hermes-Control": "1"})
    try:
        with _urlreq.urlopen(req, timeout=5) as resp:
            return _json.loads(resp.read())
    except _urlerr.HTTPError as e:
        return _json.loads(e.read())
    except (_urlerr.URLError, OSError) as e:
        return {"error": str(e)}


def _hermes_send_message(text: str, mode: str = "queue") -> dict:
    """Send a message/command to the running Hermes agent. Stdlib-only, no deps."""
    url = f"http://127.0.0.1:{_hermes_port()}/sessions/_any/message"
    data = _json.dumps({"text": text, "mode": mode}).encode()
    req = _urlreq.Request(url, data=data, method="POST",
                          headers={"Content-Type": "application/json",
                                   "X-Hermes-Control": "1"})
    try:
        with _urlreq.urlopen(req, timeout=5) as resp:
            return _json.loads(resp.read())
    except _urlerr.HTTPError as e:
        return _json.loads(e.read())
    except (_urlerr.URLError, OSError) as e:
        return {"error": str(e)}


def _resolve_hermes_model(phase: str, hermes_models: dict) -> str | None:
    """Resolve a phase to a 'provider:model' string from hermes_models config.

    Lookup: exact phase → coarse phase → 'review' (fallback for non-execute).
    Returns None if no model is configured for this phase.
    """
    spec = hermes_models.get(phase)
    if not spec:
        coarse = COARSE_PHASE_MAP.get(phase)
        if coarse:
            spec = hermes_models.get(coarse)
    if not spec and phase not in _NON_POSTFLIGHT:
        spec = hermes_models.get("review")
    return spec or None


def _switch_hermes_model(phase: str) -> bool:
    """Switch the running Hermes agent's model based on the phase.

    Reads model mapping from hermes_models in config.json.
    Returns True if switch was triggered.
    """
    if not _hermes_available():
        return False

    try:
        config = load_config()
    except (OSError, ValueError):
        return False

    hermes_models = config.get("hermes_models", {})
    if not hermes_models:
        return False

    spec = _resolve_hermes_model(phase, hermes_models)
    if not spec:
        return False

    try:
        result = _hermes_send_message(f"/model {spec}", mode="interrupt")
        if result.get("success"):
            _hermes_send_message("continue", mode="queue")
            print(f"🔄 Hermes model → {spec} (phase: {phase})")
            return True
        else:
            logger.debug("Hermes model switch failed: %s", result.get("error", ""))
            return False
    except Exception as exc:
        logger.debug("Hermes model switch skipped: %s", exc)
        return False


_AUTOREPLY_PROMPT = (
    "You are an autonomous code repair agent working through a desloppify queue. "
    "After each task, run the next desloppify command as instructed. "
    "Do not stop or ask for confirmation — keep going until the queue is empty."
)


def _ensure_hermes_autoreply() -> None:
    """Enable autoreply on the Hermes session if not already active.

    Checks the session state via GET /sessions/_any. If autoreply is
    already enabled, does nothing — so it's safe to call on every
    phase transition without clobbering an existing config.
    """
    if not _hermes_available():
        return
    try:
        info = _hermes_get("/sessions/_any")
        if info.get("autoreply", {}).get("enabled"):
            return
        _hermes_send_message(
            f"/autoreply {_AUTOREPLY_PROMPT}",
            mode="queue",
        )
        logger.debug("Hermes autoreply enabled for desloppify session")
    except Exception as exc:
        logger.debug("Hermes autoreply check skipped: %s", exc)


def emit_transition_message(new_phase: str) -> bool:
    """Print a transition message if one is configured for *new_phase*.

    Lookup order: exact phase → coarse phase → ``postflight`` (if the
    phase is not execute/scan).

    Also triggers a Hermes model switch if the control API is available.

    Returns True if a message was emitted.
    """
    # Ensure autoreply is enabled so the agent keeps working autonomously
    _ensure_hermes_autoreply()

    # Switch Hermes model for this phase (best-effort, non-blocking)
    _switch_hermes_model(new_phase)

    try:
        config = load_config()
    except (OSError, ValueError) as exc:
        logger.debug("transition message skipped (config load): %s", exc)
        return False

    messages = config.get("transition_messages")
    if not isinstance(messages, dict) or not messages:
        return False

    # Try exact phase first, then coarse fallback, then postflight.
    text = messages.get(new_phase)
    if text is None:
        coarse = COARSE_PHASE_MAP.get(new_phase)
        if coarse and coarse != new_phase:
            text = messages.get(coarse)
    if text is None and new_phase not in _NON_POSTFLIGHT:
        text = messages.get("postflight")

    if not isinstance(text, str) or not text.strip():
        return False

    clean = text.strip()
    print(f"\n{'─' * 60}")
    print(f"TRANSITION INSTRUCTION — entering {new_phase} phase")
    print(clean)
    print(f"{'─' * 60}")
    print_user_message(f"Hey, did you see the above? Please act on this: {clean}")
    return True


__all__ = ["emit_transition_message"]
