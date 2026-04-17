"""Structured evidence parsing and validation for triage stage submissions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

VERDICT_KEYWORDS = frozenset({
    "genuine",
    "false positive",
    "false-positive",
    "exaggerated",
    "over-engineering",
    "over engineering",
    "not-worth-it",
    "not worth it",
})

# Permissive path regex — detects whether *any* file path was mentioned.
# NOT used to validate existence (that's enrich-only in validation.enrich_checks).
_EVIDENCE_PATH_RE = re.compile(r"[\w.@-]+/[\w./@-]+\.\w+")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EvidenceFailure:
    """A single evidence validation failure."""

    code: str
    message: str
    blocking: bool = True


@dataclass
class ObserveAssessment:
    """A parsed per-issue assessment from an observe report (template format)."""

    issue_hash: str
    verdict: str  # normalised keyword
    verdict_reasoning: str = ""
    files_read: list[str] = field(default_factory=list)
    recommendation: str = ""


@dataclass
class ObserveEvidence:
    """Parsed observe-report evidence."""

    entries: list[ObserveAssessment] = field(default_factory=list)
    unparsed_citation_count: int = 0  # hashes cited without a verdict
    has_parseable_ids: bool = True  # False if valid_ids had no parseable short IDs


@dataclass
class ClusterVerdict:
    """A cluster-level verdict from observe-stage sampling."""

    cluster_name: str
    verdict: str  # "actionable", "mostly-false-positives", "mixed", "low-value"
    sample_count: int = 0
    false_positive_rate: float = 0.0
    recommendation: str = ""  # "promote", "skip", "break_up"


@dataclass
class DecisionLedger:
    """Parsed keep/tighten/skip coverage from a value-check report."""

    entries: dict[str, str] = field(default_factory=dict)
    duplicates: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# OBSERVE evidence parsing — structured template format
# ---------------------------------------------------------------------------

def _normalise_verdict(raw: str) -> str | None:
    """Return a normalised verdict keyword, or None if not recognised."""
    lower = raw.lower().strip()
    for kw in VERDICT_KEYWORDS:
        if kw in lower:
            # Normalise to canonical form
            canonical = kw.replace("-", " ")
            return canonical
    return None


def _build_short_map(valid_ids: set[str]) -> dict[str, str]:
    """Build collision-safe short-id → full-id map from valid issue IDs."""
    short_map: dict[str, str] = {}
    for fid in valid_ids:
        short = fid.rsplit("::", 1)[-1].lower()
        if not short:
            continue
        existing = short_map.get(short)
        if existing is None:
            short_map[short] = fid
            continue
        if existing != fid:
            short_map.pop(short, None)
    return short_map


def _is_valid_hash(raw_hash: str, short_map: dict[str, str], valid_ids: set[str]) -> bool:
    """Check if a hash is known in either the short map or valid IDs."""
    return raw_hash in short_map or raw_hash in valid_ids


# --- YAML-like template parser ---

# Matches lines like:  - hash: abc12345  or  hash: task_param_bag
_YAML_HASH_RE = re.compile(r"^\s*-?\s*hash\s*:\s*(\S+)", re.IGNORECASE)
# Matches lines like:  verdict: genuine  or  verdict: false-positive
_YAML_VERDICT_RE = re.compile(r"^\s*verdict\s*:\s*(.+)", re.IGNORECASE)
# Matches lines like:  verdict_reasoning: some reason
_YAML_REASONING_RE = re.compile(r"^\s*verdict_reasoning\s*:\s*(.+)", re.IGNORECASE)
# Matches lines like:  files_read: [src/foo.ts, src/bar.ts]  or  files_read: src/foo.ts
_YAML_FILES_RE = re.compile(r"^\s*files_read\s*:\s*(.+)", re.IGNORECASE)
# Matches lines like:  recommendation: do something
_YAML_RECOMMENDATION_RE = re.compile(r"^\s*recommendation\s*:\s*(.+)", re.IGNORECASE)

def _parse_yaml_files_field(raw: str) -> list[str]:
    """Parse the files_read field — supports [a, b] list or single path."""
    raw = raw.strip()
    # Strip surrounding brackets
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    # Split on commas
    paths = [p.strip().strip("'\"") for p in raw.split(",")]
    return [p for p in paths if p]


def _flush_yaml_entry(
    current: dict,
    short_map: dict[str, str],
    valid_ids: set[str],
) -> ObserveAssessment | None:
    """Convert a collected YAML-like entry dict into an ObserveAssessment, or None if invalid."""
    raw_hash = current.get("hash", "").lower()
    if not raw_hash or not _is_valid_hash(raw_hash, short_map, valid_ids):
        return None
    raw_verdict = current.get("verdict", "")
    verdict = _normalise_verdict(raw_verdict)
    if not verdict:
        return None
    return ObserveAssessment(
        issue_hash=raw_hash,
        verdict=verdict,
        verdict_reasoning=current.get("verdict_reasoning", ""),
        files_read=current.get("files_read", []),
        recommendation=current.get("recommendation", ""),
    )


def _parse_yaml_template(
    report: str,
    short_map: dict[str, str],
    valid_ids: set[str],
) -> list[ObserveAssessment]:
    """Parse YAML-like template entries from report text."""
    entries: list[ObserveAssessment] = []
    current: dict | None = None

    for line in report.splitlines():
        m_hash = _YAML_HASH_RE.match(line)
        if m_hash:
            # Flush previous entry
            if current is not None:
                entry = _flush_yaml_entry(current, short_map, valid_ids)
                if entry:
                    entries.append(entry)
            current = {"hash": m_hash.group(1).lower()}
            continue

        if current is None:
            continue

        m_verdict = _YAML_VERDICT_RE.match(line)
        if m_verdict:
            current["verdict"] = m_verdict.group(1).strip()
            continue

        m_reasoning = _YAML_REASONING_RE.match(line)
        if m_reasoning:
            current["verdict_reasoning"] = m_reasoning.group(1).strip()
            continue

        m_files = _YAML_FILES_RE.match(line)
        if m_files:
            current["files_read"] = _parse_yaml_files_field(m_files.group(1))
            continue

        m_rec = _YAML_RECOMMENDATION_RE.match(line)
        if m_rec:
            current["recommendation"] = m_rec.group(1).strip()
            continue

    # Flush final entry
    if current is not None:
        entry = _flush_yaml_entry(current, short_map, valid_ids)
        if entry:
            entries.append(entry)

    return entries


def parse_observe_evidence(report: str, valid_ids: set[str]) -> ObserveEvidence:
    """Parse assessment entries from an observe-stage report.

    Supports the YAML-like template format:
    hash/verdict/verdict_reasoning/files_read/recommendation
    """
    short_map = _build_short_map(valid_ids)
    entries = _parse_yaml_template(report, short_map, valid_ids)

    # Count short IDs that appear in report but weren't parsed as entries.
    valid_short_hashes = set(short_map.keys())
    all_hashes_in_report = {
        match.group(1).lower()
        for line in report.splitlines()
        if (match := _YAML_HASH_RE.match(line))
    }
    cited_hashes = all_hashes_in_report & valid_short_hashes
    parsed_hashes = {e.issue_hash for e in entries}
    unparsed = len(cited_hashes - parsed_hashes)

    return ObserveEvidence(
        entries=entries,
        unparsed_citation_count=unparsed,
        has_parseable_ids=bool(short_map),
    )


# ---------------------------------------------------------------------------
# OBSERVE evidence validation — field presence only
# ---------------------------------------------------------------------------

_OBSERVE_TEMPLATE_HINT = (
    "  Required template per issue:\n"
    "    - hash: <hash>\n"
    "      verdict: genuine | false-positive | exaggerated | over-engineering | not-worth-it\n"
    "      verdict_reasoning: <why this verdict>\n"
    "      files_read: [<file paths>]\n"
    "      recommendation: <what to do>"
)


def validate_observe_evidence(
    evidence: ObserveEvidence,
    issue_count: int,
) -> list[EvidenceFailure]:
    """Validate parsed observe evidence — field presence only, no quality thresholds."""
    if issue_count == 0:
        return []

    # If valid_ids contained no parseable short IDs, verdict parsing is impossible — skip.
    if not evidence.has_parseable_ids:
        return []

    failures: list[EvidenceFailure] = []

    if not evidence.entries:
        failures.append(EvidenceFailure(
            code="no_verdicts",
            message=(
                "No per-issue assessment entries found in report.\n"
                "\n"
                f"{_OBSERVE_TEMPLATE_HINT}\n"
                "\n"
                "  Example:\n"
                "    - hash: 34580232\n"
                "      verdict: false-positive\n"
                "      verdict_reasoning: Uses branded string union KnownTaskType\n"
                "      files_read: [src/types/database.ts]\n"
                "      recommendation: No action needed"
            ),
        ))
        return failures

    # Check field presence — no quality thresholds
    missing_reasoning: list[ObserveAssessment] = []
    missing_files: list[ObserveAssessment] = []
    missing_recommendation: list[ObserveAssessment] = []

    for entry in evidence.entries:
        if not entry.verdict_reasoning.strip():
            missing_reasoning.append(entry)
        if not entry.files_read:
            missing_files.append(entry)
        if not entry.recommendation.strip():
            missing_recommendation.append(entry)

    if missing_reasoning:
        examples = "\n".join(
            f"    [{e.issue_hash}] {e.verdict}" for e in missing_reasoning[:5]
        )
        failures.append(EvidenceFailure(
            code="missing_verdict_reasoning",
            message=(
                f"{len(missing_reasoning)} of {len(evidence.entries)} assessment(s) "
                f"have no verdict_reasoning.\n"
                "\n"
                f"{_OBSERVE_TEMPLATE_HINT}\n"
                "\n"
                f"  Entries missing reasoning:\n{examples}"
            ),
        ))

    if missing_files:
        examples = "\n".join(
            f"    [{e.issue_hash}] {e.verdict}" for e in missing_files[:5]
        )
        failures.append(EvidenceFailure(
            code="missing_files_read",
            message=(
                f"{len(missing_files)} of {len(evidence.entries)} assessment(s) "
                f"have no files_read.\n"
                "\n"
                f"{_OBSERVE_TEMPLATE_HINT}\n"
                "\n"
                f"  Entries missing files_read:\n{examples}"
            ),
        ))

    if missing_recommendation:
        examples = "\n".join(
            f"    [{e.issue_hash}] {e.verdict}" for e in missing_recommendation[:5]
        )
        failures.append(EvidenceFailure(
            code="missing_recommendation",
            message=(
                f"{len(missing_recommendation)} of {len(evidence.entries)} assessment(s) "
                f"have no recommendation.\n"
                "\n"
                f"{_OBSERVE_TEMPLATE_HINT}\n"
                "\n"
                f"  Entries missing recommendation:\n{examples}"
            ),
        ))

    return failures


# ---------------------------------------------------------------------------
# REFLECT skip-reason validation
# ---------------------------------------------------------------------------

_SKIP_LINE_RE = re.compile(
    r"(?:skip|dismiss|defer|drop|remove)\s*:\s*\[?([0-9a-f]{6,})\]?\s*[(\-—–:]*\s*(.+)",
    re.IGNORECASE,
)


def validate_reflect_skip_evidence(report: str) -> list[EvidenceFailure]:
    """Validate that skip reasons in a reflect report are non-empty."""
    failures: list[EvidenceFailure] = []
    bad_skips: list[tuple[str, str]] = []

    for line in report.splitlines():
        m = _SKIP_LINE_RE.search(line)
        if not m:
            continue
        issue_hash = m.group(1)
        reason = m.group(2).strip().rstrip(")")

        # Just check non-empty reason
        if not reason.strip():
            bad_skips.append((issue_hash, reason))

    if bad_skips:
        failing_examples = "\n".join(
            f'    [{h}] "{r}"' for h, r in bad_skips[:5]
        )
        failures.append(EvidenceFailure(
            code="vague_skip_reason",
            message=(
                f"{len(bad_skips)} skip reason(s) are empty.\n"
                "\n"
                "  Required format:\n"
                "    Skip: [<hash>] (<reason for skipping>)\n"
                "\n"
                f"  Failing skips:\n{failing_examples}"
            ),
        ))

    return failures


# ---------------------------------------------------------------------------
# Cluster-name mention check (organize + sense-check)
# ---------------------------------------------------------------------------

def validate_report_references_clusters(
    report: str,
    cluster_names: list[str],
) -> list[EvidenceFailure]:
    """Check that at least one cluster name appears in the report."""
    if not cluster_names:
        return []

    report_lower = report.lower()
    for name in cluster_names:
        if name.lower() in report_lower:
            return []

    failures: list[EvidenceFailure] = []
    names_str = ", ".join(cluster_names[:5])
    if len(cluster_names) > 5:
        names_str += f" ... ({len(cluster_names)} total)"
    failures.append(EvidenceFailure(
        code="no_cluster_mention",
        message=(
            f"Report references none of the {len(cluster_names)} cluster name(s).\n"
            "\n"
            "  The report must mention at least one cluster by name to prove\n"
            "  awareness of the plan structure.\n"
            "\n"
            f"  Cluster names: {names_str}"
        ),
    ))
    return failures


# ---------------------------------------------------------------------------
# File path mention check (sense-check)
# ---------------------------------------------------------------------------

def validate_report_has_file_paths(report: str) -> list[EvidenceFailure]:
    """Check that at least one file path appears in the report."""
    if _EVIDENCE_PATH_RE.search(report):
        return []
    return [EvidenceFailure(
        code="no_file_paths_in_report",
        message=(
            "Report references no file paths (need at least 1).\n"
            "\n"
            "  The sense-check report must prove code was read. Include specific\n"
            "  file paths and line numbers for verified steps.\n"
            "\n"
            "  Example:\n"
            "    Verified src/services/funds.ts lines 45-67: function signature\n"
            "    matches step description. Effort tag 'small' is accurate."
        ),
    )]


# ---------------------------------------------------------------------------
# Cluster-level verdict parsing (observe stage)
# ---------------------------------------------------------------------------

_CLUSTER_VERDICT_KEYWORDS = frozenset({
    "actionable", "mostly-false-positives", "mostly false positives",
    "mixed", "low-value", "low value",
})

# Matches:  - cluster: auto/security-B602
_YAML_CLUSTER_RE = re.compile(r"^\s*-?\s*cluster\s*:\s*(\S+)", re.IGNORECASE)
_YAML_SAMPLE_COUNT_RE = re.compile(r"^\s*sample_count\s*:\s*(\d+)", re.IGNORECASE)
_YAML_FP_RATE_RE = re.compile(r"^\s*false_positive_rate\s*:\s*([\d.]+)", re.IGNORECASE)


def parse_cluster_verdicts(report: str) -> list[ClusterVerdict]:
    """Parse cluster-level verdicts from an observe-stage report.

    Supports YAML-like format:
        - cluster: auto/security-B602
          verdict: mostly-false-positives
          sample_count: 5
          false_positive_rate: 0.8
          recommendation: skip
    """
    verdicts: list[ClusterVerdict] = []
    current: dict | None = None

    for line in report.splitlines():
        m_cluster = _YAML_CLUSTER_RE.match(line)
        if m_cluster:
            if current is not None:
                v = _flush_cluster_verdict(current)
                if v:
                    verdicts.append(v)
            current = {"cluster": m_cluster.group(1).strip()}
            continue

        if current is None:
            continue

        m_verdict = _YAML_VERDICT_RE.match(line)
        if m_verdict:
            current["verdict"] = m_verdict.group(1).strip()
            continue

        m_sample = _YAML_SAMPLE_COUNT_RE.match(line)
        if m_sample:
            current["sample_count"] = int(m_sample.group(1))
            continue

        m_fp = _YAML_FP_RATE_RE.match(line)
        if m_fp:
            try:
                current["false_positive_rate"] = float(m_fp.group(1))
            except ValueError:
                pass
            continue

        m_rec = _YAML_RECOMMENDATION_RE.match(line)
        if m_rec:
            current["recommendation"] = m_rec.group(1).strip()
            continue

    if current is not None:
        v = _flush_cluster_verdict(current)
        if v:
            verdicts.append(v)

    return verdicts


def _flush_cluster_verdict(current: dict) -> ClusterVerdict | None:
    """Convert a collected cluster verdict dict into a ClusterVerdict."""
    cluster_name = current.get("cluster", "")
    if not cluster_name:
        return None
    raw_verdict = current.get("verdict", "")
    # Accept any verdict text (don't enforce keywords — let the LLM express itself)
    if not raw_verdict:
        return None
    return ClusterVerdict(
        cluster_name=cluster_name,
        verdict=raw_verdict.lower().strip(),
        sample_count=current.get("sample_count", 0),
        false_positive_rate=current.get("false_positive_rate", 0.0),
        recommendation=current.get("recommendation", ""),
    )


_VALUE_LEDGER_RE = re.compile(
    r"^\s*-\s*(?P<target>.+?)\s*->\s*(?P<decision>keep|tighten|skip)\s*$",
    re.IGNORECASE,
)


def parse_value_check_decision_ledger(report: str) -> DecisionLedger:
    """Parse `## Decision Ledger` lines from a value-check report."""
    entries: dict[str, str] = {}
    duplicates: list[str] = []
    for line in report.splitlines():
        match = _VALUE_LEDGER_RE.match(line)
        if match is None:
            continue
        target = match.group("target").strip()
        decision = match.group("decision").strip().lower()
        if target in entries:
            duplicates.append(target)
            continue
        entries[target] = decision
    return DecisionLedger(entries=entries, duplicates=duplicates)


# ---------------------------------------------------------------------------
# Shared output helpers
# ---------------------------------------------------------------------------

def format_evidence_failures(
    failures: list[EvidenceFailure],
    *,
    stage_label: str,
) -> str:
    """Format evidence failures into a single rejection message."""
    blocking = [f for f in failures if f.blocking]
    advisory = [f for f in failures if not f.blocking]
    parts: list[str] = []

    for f in blocking:
        parts.append(f"  REJECTED: {f.message}")

    for f in advisory:
        parts.append(f"  Warning: {f.message}")

    return "\n\n".join(parts)


def resolve_short_hash_to_full_id(short_hash: str, valid_ids: set[str]) -> str | None:
    """Resolve a short hash to a full issue ID using collision-aware resolution.

    Uses ``_build_id_resolution_maps`` from reflect_accounting to handle
    ambiguous short hashes safely (drops collisions rather than silently
    overwriting).
    """
    from ..validation.reflect_accounting import _build_id_resolution_maps

    maps = _build_id_resolution_maps(valid_ids)
    # Try direct match first
    if short_hash in valid_ids:
        return short_hash
    short_hash = short_hash.lower()
    bucket = maps.short_id_buckets.get(short_hash)
    if bucket and len(bucket) == 1:
        return bucket[0]
    # Try collision-aware short hex map
    resolved = maps.short_hex_map.get(short_hash)
    if resolved:
        return resolved
    return None


__all__ = [
    "ClusterVerdict",
    "DecisionLedger",
    "EvidenceFailure",
    "ObserveAssessment",
    "ObserveEvidence",
    "VERDICT_KEYWORDS",
    "format_evidence_failures",
    "parse_cluster_verdicts",
    "parse_value_check_decision_ledger",
    "parse_observe_evidence",
    "resolve_short_hash_to_full_id",
    "validate_observe_evidence",
    "validate_reflect_skip_evidence",
    "validate_report_has_file_paths",
    "validate_report_references_clusters",
]
