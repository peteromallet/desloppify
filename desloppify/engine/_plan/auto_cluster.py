"""Auto-clustering algorithm — groups findings into task clusters."""

from __future__ import annotations

import os
from collections import defaultdict

from desloppify.core.registry import DETECTORS, DetectorMeta
from desloppify.engine._plan.schema import Cluster, PlanModel, ensure_plan_defaults
from desloppify.engine._plan.stale_dimensions import (
    SUBJECTIVE_PREFIX,
    _current_unscored_ids,
)
from desloppify.engine._state.schema import StateModel, utc_now

AUTO_PREFIX = "auto/"
_MIN_CLUSTER_SIZE = 2
_STALE_KEY = "subjective::stale"
_STALE_NAME = "auto/stale-review"
_UNSCORED_KEY = "subjective::unscored"
_UNSCORED_NAME = "auto/initial-review"
_MIN_UNSCORED_CLUSTER_SIZE = 1


# ---------------------------------------------------------------------------
# Grouping key computation
# ---------------------------------------------------------------------------

def _extract_subtype(finding: dict) -> str | None:
    """Extract the subtype/kind from a finding.

    Checks detail.kind first, then falls back to parsing the finding ID
    (format: ``detector::file::subtype`` or ``detector::file::symbol::subtype``).
    """
    detail = finding.get("detail") or {}
    kind = detail.get("kind")
    if kind:
        return kind

    # Parse from finding ID — third segment is often the subtype
    fid = finding.get("id", "")
    parts = fid.split("::")
    if len(parts) >= 3:
        # For IDs like smells::file.py::silent_except, the subtype is parts[2]
        # For IDs like dict_keys::file.py::key::phantom_read, subtype is last part
        candidate = parts[-1]
        # Skip if it looks like a file path or symbol name (contains / or .)
        if "/" not in candidate and "." not in candidate:
            return candidate
    return None


def _grouping_key(finding: dict, meta: DetectorMeta | None) -> str | None:
    """Compute a deterministic grouping key for a finding.

    Returns None if the finding should not be auto-clustered.
    """
    detector = finding.get("detector", "")

    if meta is None:
        # Unknown detector — group by detector name
        return f"detector::{detector}"

    # Review findings → group by dimension
    if detector in ("review", "subjective_review"):
        detail = finding.get("detail") or {}
        dimension = detail.get("dimension", "")
        if dimension:
            return f"review::{dimension}"
        return f"detector::{detector}"

    # Per-file detectors (structural, responsibility_cohesion)
    if meta.needs_judgment and detector in (
        "structural", "responsibility_cohesion",
    ):
        file = finding.get("file", "")
        if file:
            basename = os.path.basename(file)
            return f"file::{detector}::{basename}"

    # Needs-judgment detectors — group by subtype when available
    if meta.needs_judgment:
        subtype = _extract_subtype(finding)
        if subtype:
            return f"typed::{detector}::{subtype}"

    # Pure auto-fix (no judgment needed) → all findings by detector
    if meta.action_type == "auto_fix" and not meta.needs_judgment:
        return f"auto::{detector}"

    # Everything else → by detector
    return f"detector::{detector}"


def _cluster_name_from_key(key: str) -> str:
    """Convert a grouping key to a cluster name with auto/ prefix."""
    # auto::unused → auto/unused
    # typed::dict_keys::phantom_read → auto/dict_keys-phantom_read
    # file::structural::big_file.py → auto/structural-big_file.py
    # review::abstraction_fitness → auto/review-abstraction_fitness
    # detector::security → auto/security
    parts = key.split("::")
    if len(parts) == 2:
        prefix_type = parts[0]
        # For review keys, keep the prefix for clarity
        if prefix_type == "review":
            return f"{AUTO_PREFIX}review-{parts[1]}"
        return f"{AUTO_PREFIX}{parts[1]}"
    if len(parts) == 3:
        return f"{AUTO_PREFIX}{parts[1]}-{parts[2]}"
    return f"{AUTO_PREFIX}{key.replace('::', '-')}"


# ---------------------------------------------------------------------------
# Description and action generation
# ---------------------------------------------------------------------------

def _generate_description(
    cluster_name: str,
    members: list[dict],
    meta: DetectorMeta | None,
    subtype: str | None,
) -> str:
    """Generate a human-readable cluster description."""
    count = len(members)
    detector = members[0].get("detector", "") if members else ""

    if detector in ("review", "subjective_review"):
        detail = (members[0].get("detail") or {}) if members else {}
        dimension = detail.get("dimension", detector)
        return f"Address {count} {dimension} review findings"

    if detector == "structural":
        files = {os.path.basename(m.get("file", "")) for m in members}
        if len(files) == 1:
            return f"Decompose {next(iter(files))}"
        return f"Decompose {count} large files"

    display = meta.display if meta else detector
    if subtype:
        label = subtype.replace("_", " ")
        return f"Fix {count} {label} issues"

    if meta and meta.action_type == "auto_fix" and not meta.needs_judgment:
        return f"Remove {count} {display} findings"

    return f"Fix {count} {display} issues"


def _subtype_has_fixer(meta: DetectorMeta, subtype: str | None) -> str | None:
    """Check if a subtype maps to a specific fixer."""
    if not meta.fixers or not subtype:
        return None
    # Convention: fixer name is subtype with _ replaced by -
    fixer_name = subtype.replace("_", "-")
    if fixer_name in meta.fixers:
        return fixer_name
    # Also check if subtype is a substring (e.g. "unused" matches "unused-imports")
    for fixer in meta.fixers:
        if subtype in fixer:
            return fixer
    return None


def _strip_guidance_examples(guidance: str) -> str:
    """Strip subtype-specific examples from guidance text.

    Many guidance strings have format "verb — specific examples".
    Strip after the dash to get the core action:
      "fix code smells — dead useEffect, empty if chains" → "fix code smells"
    """
    if " — " in guidance:
        return guidance.split(" — ", 1)[0].strip()
    return guidance


_ACTION_TYPE_TEMPLATES: dict[str, str] = {
    "reorganize": "reorganize with desloppify move",
    "refactor": "review and refactor each finding",
    "manual_fix": "review and fix each finding",
}


def _generate_action(
    meta: DetectorMeta | None,
    subtype: str | None,
) -> str:
    """Generate an action string from detector metadata.

    Always returns a non-empty string — every cluster gets an action.
    """
    if meta is None:
        return "review and fix each finding"

    # For detectors with subtypes, only suggest a fixer if the subtype matches
    if subtype and meta.fixers:
        matched_fixer = _subtype_has_fixer(meta, subtype)
        if matched_fixer:
            return f"desloppify fix {matched_fixer} --dry-run"
    elif meta.action_type == "auto_fix" and meta.fixers and not meta.needs_judgment:
        # Pure auto-fix detector, no subtypes
        return f"desloppify fix {meta.fixers[0]} --dry-run"

    if meta.tool == "move":
        return "desloppify move"

    # Guidance available — use it (strip examples for subtyped detectors)
    if meta.guidance:
        if subtype:
            return _strip_guidance_examples(meta.guidance)
        return meta.guidance

    # Final fallback: action_type template
    return _ACTION_TYPE_TEMPLATES.get(
        meta.action_type, "review and fix each finding"
    )


# ---------------------------------------------------------------------------
# Main algorithm
# ---------------------------------------------------------------------------

def auto_cluster_findings(plan: PlanModel, state: StateModel) -> int:
    """Regenerate auto-clusters from current open findings.

    Returns count of changes made (clusters created, updated, or deleted).
    """
    ensure_plan_defaults(plan)
    changes = 0

    findings = state.get("findings", {})
    clusters = plan.get("clusters", {})

    # Set of finding IDs in manual (non-auto) clusters
    manual_member_ids: set[str] = set()
    for cluster in clusters.values():
        if not cluster.get("auto"):
            manual_member_ids.update(cluster.get("finding_ids", []))

    # Collect open, non-suppressed findings and group by key
    groups: dict[str, list[str]] = defaultdict(list)
    finding_data: dict[str, dict] = {}
    for fid, finding in findings.items():
        if finding.get("status") != "open":
            continue
        if finding.get("suppressed"):
            continue
        if fid in manual_member_ids:
            continue

        detector = finding.get("detector", "")
        meta = DETECTORS.get(detector)
        key = _grouping_key(finding, meta)
        if key is None:
            continue

        groups[key].append(fid)
        finding_data[fid] = finding

    # Drop singleton groups
    groups = {k: v for k, v in groups.items() if len(v) >= _MIN_CLUSTER_SIZE}

    # Map existing auto-clusters by cluster_key
    existing_by_key: dict[str, str] = {}  # cluster_key → cluster_name
    for name, cluster in list(clusters.items()):
        if cluster.get("auto"):
            ck = cluster.get("cluster_key", "")
            if ck:
                existing_by_key[ck] = name

    now = utc_now()
    active_auto_keys: set[str] = set()

    for key, member_ids in groups.items():
        active_auto_keys.add(key)
        cluster_name = _cluster_name_from_key(key)

        # Representative finding for metadata
        rep = finding_data.get(member_ids[0], {})
        detector = rep.get("detector", "")
        meta = DETECTORS.get(detector)
        members = [finding_data[fid] for fid in member_ids if fid in finding_data]

        # Extract subtype from grouping key (typed::detector::subtype)
        key_parts = key.split("::")
        subtype = key_parts[2] if len(key_parts) >= 3 else None

        description = _generate_description(cluster_name, members, meta, subtype)
        action = _generate_action(meta, subtype)

        existing_name = existing_by_key.get(key)
        if existing_name and existing_name in clusters:
            cluster = clusters[existing_name]
            if cluster.get("user_modified"):
                # Merge new findings in, don't remove user's edits
                existing_ids = set(cluster.get("finding_ids", []))
                new_ids = [fid for fid in member_ids if fid not in existing_ids]
                if new_ids:
                    cluster["finding_ids"].extend(new_ids)
                    cluster["updated_at"] = now
                    changes += 1
            else:
                # Replace membership wholesale
                old_ids = set(cluster.get("finding_ids", []))
                new_ids = set(member_ids)
                if old_ids != new_ids or cluster.get("description") != description or cluster.get("action") != action:
                    cluster["finding_ids"] = list(member_ids)
                    cluster["description"] = description
                    cluster["action"] = action
                    cluster["updated_at"] = now
                    changes += 1
        else:
            # Handle name collision (existing auto-cluster with different key)
            # If cluster_name already exists with a different key, skip
            if cluster_name in clusters and clusters[cluster_name].get("cluster_key") != key:
                # Append a disambiguator
                cluster_name = f"{cluster_name}-{len(member_ids)}"

            new_cluster: Cluster = {
                "name": cluster_name,
                "description": description,
                "finding_ids": list(member_ids),
                "created_at": now,
                "updated_at": now,
                "auto": True,
                "cluster_key": key,
                "action": action,
                "user_modified": False,
            }
            clusters[cluster_name] = new_cluster
            existing_by_key[key] = cluster_name
            changes += 1

        # Update overrides to track cluster membership
        overrides = plan.get("overrides", {})
        current_name = existing_by_key.get(key, cluster_name)
        for fid in member_ids:
            if fid not in overrides:
                overrides[fid] = {"finding_id": fid, "created_at": now}
            overrides[fid]["cluster"] = current_name
            overrides[fid]["updated_at"] = now

    # --- Subjective dimension clusters (unscored + stale) -------------------
    all_subjective_ids = sorted(
        fid for fid in plan.get("queue_order", [])
        if fid.startswith(SUBJECTIVE_PREFIX)
    )
    unscored_state_ids = _current_unscored_ids(state)
    unscored_queue_ids = sorted(
        fid for fid in all_subjective_ids if fid in unscored_state_ids
    )
    stale_queue_ids = sorted(
        fid for fid in all_subjective_ids if fid not in unscored_state_ids
    )

    # -- Initial review cluster (unscored, min size 1) ---------------------
    if len(unscored_queue_ids) >= _MIN_UNSCORED_CLUSTER_SIZE:
        active_auto_keys.add(_UNSCORED_KEY)
        cli_keys = [fid.removeprefix(SUBJECTIVE_PREFIX) for fid in unscored_queue_ids]
        description = f"Initial review of {len(unscored_queue_ids)} unscored subjective dimensions"
        action = f"desloppify review --prepare --dimensions {','.join(cli_keys)}"

        existing_name = existing_by_key.get(_UNSCORED_KEY)
        if existing_name and existing_name in clusters:
            cluster = clusters[existing_name]
            old_ids = set(cluster.get("finding_ids", []))
            new_ids = set(unscored_queue_ids)
            if old_ids != new_ids or cluster.get("description") != description or cluster.get("action") != action:
                cluster["finding_ids"] = unscored_queue_ids
                cluster["description"] = description
                cluster["action"] = action
                cluster["updated_at"] = now
                changes += 1
        else:
            clusters[_UNSCORED_NAME] = {
                "name": _UNSCORED_NAME,
                "description": description,
                "finding_ids": unscored_queue_ids,
                "created_at": now,
                "updated_at": now,
                "auto": True,
                "cluster_key": _UNSCORED_KEY,
                "action": action,
                "user_modified": False,
            }
            existing_by_key[_UNSCORED_KEY] = _UNSCORED_NAME
            changes += 1

        overrides = plan.get("overrides", {})
        current_name = existing_by_key.get(_UNSCORED_KEY, _UNSCORED_NAME)
        for fid in unscored_queue_ids:
            if fid not in overrides:
                overrides[fid] = {"finding_id": fid, "created_at": now}
            overrides[fid]["cluster"] = current_name
            overrides[fid]["updated_at"] = now

    # -- Stale review cluster (previously scored, min size 2) --------------
    if len(stale_queue_ids) >= _MIN_CLUSTER_SIZE:
        active_auto_keys.add(_STALE_KEY)
        cli_keys = [fid.removeprefix(SUBJECTIVE_PREFIX) for fid in stale_queue_ids]
        description = f"Re-review {len(stale_queue_ids)} stale subjective dimensions"
        action = (
            "desloppify review --prepare --dimensions "
            + ",".join(cli_keys)
            + " --force-review-rerun"
        )

        existing_name = existing_by_key.get(_STALE_KEY)
        if existing_name and existing_name in clusters:
            cluster = clusters[existing_name]
            old_ids = set(cluster.get("finding_ids", []))
            new_ids = set(stale_queue_ids)
            if old_ids != new_ids or cluster.get("description") != description or cluster.get("action") != action:
                cluster["finding_ids"] = stale_queue_ids
                cluster["description"] = description
                cluster["action"] = action
                cluster["updated_at"] = now
                changes += 1
        else:
            clusters[_STALE_NAME] = {
                "name": _STALE_NAME,
                "description": description,
                "finding_ids": stale_queue_ids,
                "created_at": now,
                "updated_at": now,
                "auto": True,
                "cluster_key": _STALE_KEY,
                "action": action,
                "user_modified": False,
            }
            existing_by_key[_STALE_KEY] = _STALE_NAME
            changes += 1

        overrides = plan.get("overrides", {})
        current_name = existing_by_key.get(_STALE_KEY, _STALE_NAME)
        for fid in stale_queue_ids:
            if fid not in overrides:
                overrides[fid] = {"finding_id": fid, "created_at": now}
            overrides[fid]["cluster"] = current_name
            overrides[fid]["updated_at"] = now

    # Delete stale auto-clusters (no matching group, not user_modified)
    for name in list(clusters.keys()):
        cluster = clusters[name]
        if not cluster.get("auto"):
            continue
        ck = cluster.get("cluster_key", "")
        if ck in active_auto_keys:
            continue
        if cluster.get("user_modified"):
            # Keep user-modified clusters but prune dead member IDs
            alive = [fid for fid in cluster.get("finding_ids", [])
                     if fid in findings and findings[fid].get("status") == "open"]
            if alive:
                if len(alive) != len(cluster.get("finding_ids", [])):
                    cluster["finding_ids"] = alive
                    cluster["updated_at"] = now
                    changes += 1
                continue
            # All members gone — delete even if user_modified
        # Delete stale cluster
        del clusters[name]
        # Clear cluster refs from overrides
        for fid in cluster.get("finding_ids", []):
            override = plan.get("overrides", {}).get(fid)
            if override and override.get("cluster") == name:
                override["cluster"] = None
                override["updated_at"] = now
        if plan.get("active_cluster") == name:
            plan["active_cluster"] = None
        changes += 1

    plan["updated"] = now
    return changes


__all__ = [
    "AUTO_PREFIX",
    "auto_cluster_findings",
]
