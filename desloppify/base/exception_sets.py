"""Shared exception tuples used across command/render flows."""

from __future__ import annotations

import json


class CommandError(Exception):
    """Raised by command helpers to signal a user-facing CLI error.

    The CLI entrypoint catches this and prints ``message`` to stderr
    before exiting with ``exit_code``.  Helpers should raise this instead
    of calling ``sys.exit()`` directly so that the error path is testable
    and composable.
    """

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        self.message = message
        self.exit_code = exit_code
        super().__init__(message)


class PacketValidationError(CommandError):
    """Raised for malformed/missing review packet inputs."""


class ScanQueueBlockedError(CommandError):
    """Raised when an unfinished execution queue defers the next scan."""


class RunnerTimeoutError(CommandError):
    """Raised when review batch execution fails due to timeout conditions."""


class TriageValidationError(CommandError):
    """Raised for invalid triage-stage attestation or workflow inputs."""


PLAN_LOAD_EXCEPTIONS = (
    OSError,
    ValueError,
    UnicodeDecodeError,
    json.JSONDecodeError,
)

__all__ = [
    "CommandError",
    "PLAN_LOAD_EXCEPTIONS",
    "PacketValidationError",
    "RunnerTimeoutError",
    "ScanQueueBlockedError",
    "TriageValidationError",
]
