"""Persona rotation for parallel review batches.

When multiple review batches run in parallel, each batch can adopt a
different reviewer persona.  The persona biases *attention*, not scoring
rules: all findings still require the same confidence thresholds.

Personas improve coverage diversity -- a Bug Hunter notices edge-case
races that an Architect overlooks, while the Architect catches boundary
violations the Pragmatist skips.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    """A reviewer persona that biases attention during batch review."""

    name: str
    bias: str
    key_question: str


PERSONAS: tuple[Persona, ...] = (
    Persona(
        name="Pragmatist",
        bias="Simplicity over cleverness",
        key_question="Would a new team member understand this in 30 seconds?",
    ),
    Persona(
        name="Architect",
        bias="Boundaries, coupling, API surface consistency, and layer discipline",
        key_question="Does this respect the system's structural contracts?",
    ),
    Persona(
        name="Bug Hunter",
        bias="Null/undefined, race conditions, missing awaits, error swallowing, and edge cases",
        key_question="What fails under edge cases or concurrent access?",
    ),
    Persona(
        name="Migrator",
        bias="Deprecated patterns, half-migrated code, stale shims, and dual-path confusion",
        key_question="What should have been cleaned up already?",
    ),
)


def assign_personas(batch_count: int) -> list[Persona | None]:
    """Return a persona assignment for *batch_count* batches.

    Cycles through the four personas.  When there are more batches than
    personas, the cycle repeats.  Returns ``None`` entries only when
    ``batch_count`` is zero.
    """
    if batch_count <= 0:
        return []
    return [PERSONAS[i % len(PERSONAS)] for i in range(batch_count)]


def render_persona_block(persona: Persona | None) -> str:
    """Render a prompt section describing the active persona."""
    if persona is None:
        return ""
    return (
        f"REVIEWER PERSONA: {persona.name}\n"
        f"Attention bias: {persona.bias}\n"
        f"Key question: {persona.key_question}\n\n"
        "The persona biases where you spend your attention, not the scoring "
        "rules. All findings still require the standard confidence threshold. "
        "You still report every issue you find, but you explore your "
        "persona's domain more thoroughly than other areas.\n\n"
    )


__all__ = [
    "PERSONAS",
    "Persona",
    "assign_personas",
    "render_persona_block",
]
