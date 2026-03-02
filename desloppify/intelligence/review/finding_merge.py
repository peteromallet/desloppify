"""Shared finding-merge primitives.

Both ``app/commands/review/merge.py`` (post-import CLI) and
``app/commands/review/batch_core.py`` (batch accumulation) need the same
dedup-and-merge mechanics.  Extracting them here prevents drift.
"""

from __future__ import annotations

from collections.abc import Sequence


def normalize_word_set(text: str) -> set[str]:
    """Tokenize *text* into lowercase words >= 3 chars."""
    words = "".join(ch.lower() if ch.isalnum() else " " for ch in text).split()
    return {word for word in words if len(word) >= 3}


def merge_list_fields(
    target: dict, source: dict, fields: Sequence[str]
) -> None:
    """Deduplicated merge of list *fields* from *source* into *target*."""
    for field in fields:
        merged: list[str] = []
        seen: set[str] = set()
        for src in (target.get(field), source.get(field)):
            if not isinstance(src, list):
                continue
            for item in src:
                value = str(item).strip()
                if not value or value in seen:
                    continue
                seen.add(value)
                merged.append(value)
        if merged:
            target[field] = merged


def pick_longer_text(target: dict, source: dict, field: str) -> None:
    """Keep the longer text value for a string *field*."""
    target_text = str(target.get(field, "")).strip()
    source_text = str(source.get(field, "")).strip()
    if len(source_text) > len(target_text):
        target[field] = source_text


def track_merged_from(target: dict, source_id: str) -> None:
    """Append *source_id* to ``target['merged_from']`` if not already present."""
    merged_from = target.get("merged_from")
    if not isinstance(merged_from, list):
        merged_from = []
    if source_id and source_id not in merged_from:
        merged_from.append(source_id)
    if merged_from:
        target["merged_from"] = merged_from
