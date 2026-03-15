"""Reflect-stage coverage-ledger parsing and issue-accounting helpers."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from desloppify.base.output.terminal import colorize
from desloppify.engine.plan_triage import extract_issue_citations

DecisionKind = Literal["cluster", "permanent_skip"]


@dataclass(frozen=True)
class ReflectDisposition:
    """One issue's intended disposition as declared by the reflect stage."""

    issue_id: str
    decision: DecisionKind
    target: str

    def to_dict(self) -> dict:
        """Serialize for JSON persistence in ``plan.json``."""
        return {"issue_id": self.issue_id, "decision": self.decision, "target": self.target}

    @classmethod
    def from_dict(cls, data: dict | ReflectDisposition) -> ReflectDisposition:
        """Deserialize from persisted plan data, or pass through unchanged."""
        if isinstance(data, cls):
            return data
        issue_id = data.get("issue_id", "")
        target = data.get("target", "")
        decision = _decision_kind_or_none(data.get("decision")) or "cluster"
        return cls(
            issue_id=issue_id if isinstance(issue_id, str) else "",
            decision=decision,
            target=target if isinstance(target, str) else "",
        )


@dataclass(frozen=True)
class _IdResolutionMaps:
    """Pre-built lookup structures for resolving ledger tokens to issue IDs."""

    short_id_buckets: dict[str, list[str]]
    short_hex_map: dict[str, str]
    slug_prefix_map: dict[str, str]


def _build_id_resolution_maps(valid_ids: set[str]) -> _IdResolutionMaps:
    short_id_buckets: dict[str, list[str]] = {}
    short_hex_map: dict[str, str] = {}
    slug_prefix_map: dict[str, str] = {}
    ambiguous_slugs: set[str] = set()
    for issue_id in sorted(valid_ids):
        parts = issue_id.rsplit("::", 1)
        short_id = parts[-1]
        slug = parts[0] if len(parts) == 2 else ""
        short_id_buckets.setdefault(short_id, []).append(issue_id)
        if re.fullmatch(r"[0-9a-f]{8,}", short_id):
            existing = short_hex_map.get(short_id)
            if existing is None:
                short_hex_map[short_id] = issue_id
            elif existing != issue_id:
                short_hex_map.pop(short_id, None)
        if not slug:
            continue
        if slug in ambiguous_slugs:
            continue
        if slug in slug_prefix_map:
            slug_prefix_map.pop(slug)
            ambiguous_slugs.add(slug)
            continue
        slug_prefix_map[slug] = issue_id
    return _IdResolutionMaps(
        short_id_buckets=short_id_buckets,
        short_hex_map=short_hex_map,
        slug_prefix_map=slug_prefix_map,
    )


def _clean_ledger_token(raw: str) -> str:
    token = raw.strip().strip("`").strip()
    if token.startswith("[") and token.endswith("]"):
        token = token[1:-1].strip()
    return token


_CANONICAL_LEDGER_PATTERNS = (
    re.compile(r"-\s*(.+?)\s*->\s*(\w+)\s+[\"']([^\"']+)[\"']"),
    re.compile(r"-\s*(.+?)\s*->\s*(\w+)\s+(\S+.*)"),
)
_COMPAT_LEDGER_PATTERNS = (
    re.compile(r"-\s*(.+?)\s*:\s*(\w+)\s+[\"']?([^\"']+?)[\"']?\s*$"),
    re.compile(r"-\s*([^,]+),\s*(\w+),\s*[\"']?([^\"',]+?)[\"']?\s*$"),
)
_TOKEN_ONLY_PATTERNS = (
    re.compile(r"-\s*(.+?)\s*->"),
    re.compile(r"-\s+(\S+)\s*$"),
)


def _parse_ledger_line_with_patterns(
    line: str,
    patterns: tuple[re.Pattern[str], ...],
) -> tuple[str, str | None, str | None]:
    for pattern in patterns:
        match = pattern.match(line)
        if match:
            token = _clean_ledger_token(match.group(1))
            return token, match.group(2).strip().lower(), match.group(3).strip().strip("\"'")
    return "", None, None


def _parse_token_only_ledger_line(line: str) -> tuple[str, str | None, str | None]:
    for pattern in _TOKEN_ONLY_PATTERNS:
        match = pattern.match(line)
        if not match:
            continue
        token = _clean_ledger_token(match.group(1))
        if token:
            return token, None, None
    return "", None, None


def _extract_ledger_entry(line: str) -> tuple[str, str | None, str | None]:
    """Parse one ledger line into ``(token, decision, target)``."""
    token, decision, target = _parse_ledger_line_with_patterns(line, _CANONICAL_LEDGER_PATTERNS)
    if token:
        return token, decision, target

    token, decision, target = _parse_ledger_line_with_patterns(line, _COMPAT_LEDGER_PATTERNS)
    if token:
        return token, decision, target

    return _parse_token_only_ledger_line(line)


def _resolve_token_to_id(
    token: str,
    valid_ids: set[str],
    maps: _IdResolutionMaps,
    short_id_usage: Counter[str],
) -> str | None:
    if token in valid_ids:
        return token
    bucket = maps.short_id_buckets.get(token)
    if bucket:
        bucket_index = short_id_usage[token]
        resolved = bucket[bucket_index] if bucket_index < len(bucket) else bucket[-1]
        short_id_usage[token] += 1
        return resolved
    for hex_token in re.findall(r"[0-9a-f]{8,}", token):
        resolved = maps.short_hex_map.get(hex_token)
        if resolved:
            return resolved
    return maps.slug_prefix_map.get(token.lower())


_CLUSTER_DECISIONS = frozenset({"cluster"})
_SKIP_DECISIONS = frozenset({"skip", "dismiss", "defer", "drop", "remove"})


def _normalize_decision(raw: str) -> str:
    lower = raw.lower()
    if lower in _CLUSTER_DECISIONS:
        return "cluster"
    if lower in _SKIP_DECISIONS:
        return "permanent_skip"
    return lower


def _decision_kind_or_none(raw: object) -> DecisionKind | None:
    if not isinstance(raw, str):
        return None
    normalized = _normalize_decision(raw)
    if normalized == "cluster":
        return "cluster"
    if normalized == "permanent_skip":
        return "permanent_skip"
    return None


@dataclass
class _LedgerParseResult:
    """Combined output of a single pass over the Coverage Ledger section."""

    hits: Counter[str]
    dispositions: list[ReflectDisposition]
    found_section: bool


def _iter_coverage_ledger_lines(report: str) -> tuple[bool, list[str]]:
    found_section = False
    in_ledger = False
    lines: list[str] = []
    for raw_line in report.splitlines():
        line = raw_line.strip()
        if re.fullmatch(r"##\s+Coverage Ledger", line, re.IGNORECASE):
            found_section = True
            in_ledger = True
            continue
        if in_ledger and re.match(r"##\s+", line):
            break
        if in_ledger:
            lines.append(line)
    return found_section, lines


def _resolve_ledger_issue_id(
    *,
    token: str,
    line: str,
    valid_ids: set[str],
    maps: _IdResolutionMaps,
    short_id_usage: Counter[str],
) -> str | None:
    issue_id = _resolve_token_to_id(token, valid_ids, maps, short_id_usage)
    if issue_id:
        return issue_id
    for hex_token in re.findall(r"[0-9a-f]{8,}", line):
        resolved = maps.short_hex_map.get(hex_token)
        if resolved:
            return resolved
    return None


def _append_disposition_if_supported(
    dispositions: list[ReflectDisposition],
    *,
    issue_id: str,
    decision: str | None,
    target: str | None,
) -> None:
    parsed_decision = _decision_kind_or_none(decision)
    if parsed_decision is None or not target:
        return
    dispositions.append(
        ReflectDisposition(
            issue_id=issue_id,
            decision=parsed_decision,
            target=target,
        )
    )


def _walk_coverage_ledger(
    report: str,
    valid_ids: set[str],
) -> _LedgerParseResult:
    maps = _build_id_resolution_maps(valid_ids)
    hits: Counter[str] = Counter()
    dispositions: list[ReflectDisposition] = []
    short_id_usage: Counter[str] = Counter()
    found_section, ledger_lines = _iter_coverage_ledger_lines(report)

    for line in ledger_lines:
        token, decision, target = _extract_ledger_entry(line)
        if not token:
            continue

        issue_id = _resolve_ledger_issue_id(
            token=token,
            line=line,
            valid_ids=valid_ids,
            maps=maps,
            short_id_usage=short_id_usage,
        )
        if not issue_id:
            continue
        hits[issue_id] += 1
        _append_disposition_if_supported(
            dispositions,
            issue_id=issue_id,
            decision=decision,
            target=target,
        )

    return _LedgerParseResult(
        hits=hits,
        dispositions=dispositions,
        found_section=found_section,
    )


def parse_reflect_dispositions(
    report: str,
    valid_ids: set[str],
) -> list[ReflectDisposition]:
    """Parse structured dispositions from the Coverage Ledger section."""
    return _walk_coverage_ledger(report, valid_ids).dispositions


def analyze_reflect_issue_accounting(
    *,
    report: str,
    valid_ids: set[str],
) -> tuple[set[str], list[str], list[str]]:
    """Return cited, missing, and duplicate issue IDs referenced by reflect."""
    result = _walk_coverage_ledger(report, valid_ids)
    if result.found_section and result.hits:
        cited = set(result.hits)
        duplicates = sorted(issue_id for issue_id, count in result.hits.items() if count > 1)
        missing = sorted(valid_ids - cited)
        return cited, missing, duplicates

    maps = _build_id_resolution_maps(valid_ids)
    cited = extract_issue_citations(report, valid_ids)
    for issue_id in valid_ids:
        if issue_id in report:
            cited.add(issue_id)

    short_hits = _collect_legacy_short_hex_hits(report, maps)
    cited.update(short_hits)

    duplicates = sorted(issue_id for issue_id, count in short_hits.items() if count > 1)
    missing = sorted(valid_ids - cited)
    return cited, missing, duplicates


def _collect_legacy_short_hex_hits(
    report: str,
    maps: _IdResolutionMaps,
) -> Counter[str]:
    short_hits: Counter[str] = Counter()
    for token in re.findall(r"[0-9a-f]{8,}", report):
        resolved = maps.short_hex_map.get(token)
        if resolved:
            short_hits[resolved] += 1
    return short_hits


def validate_reflect_accounting(
    *,
    report: str,
    valid_ids: set[str],
) -> tuple[bool, set[str], list[str], list[str]]:
    """Require the reflect report to account for each open issue exactly once."""
    cited, missing, duplicates = analyze_reflect_issue_accounting(
        report=report,
        valid_ids=valid_ids,
    )
    if not missing and not duplicates:
        return True, cited, missing, duplicates

    print(
        colorize(
            "  Reflect report must account for every open review issue exactly once.",
            "red",
        )
    )
    if missing:
        missing_short = ", ".join(issue_id.rsplit("::", 1)[-1] for issue_id in missing[:10])
        print(colorize(f"    Missing: {missing_short}", "yellow"))
    if duplicates:
        duplicate_short = ", ".join(issue_id.rsplit("::", 1)[-1] for issue_id in duplicates[:10])
        print(colorize(f"    Duplicated: {duplicate_short}", "yellow"))
    print(colorize("  Fix the reflect blueprint before running organize.", "dim"))
    if missing:
        print(colorize("  Expected format — include a ## Coverage Ledger section:", "dim"))
        print(colorize('    - <hash> -> cluster "cluster-name"', "dim"))
        print(colorize('    - <hash> -> skip "reason"', "dim"))
        print(colorize("  Also accepted: bare hashes, colon-separated, comma-separated.", "dim"))
    return False, cited, missing, duplicates


BacklogDecisionKind = Literal["promote", "skip", "supersede"]


@dataclass(frozen=True)
class BacklogDecision:
    """One auto-cluster's intended disposition as declared by the reflect stage."""

    cluster_name: str
    decision: BacklogDecisionKind
    reason: str = ""

    def to_dict(self) -> dict:
        """Serialize for JSON persistence."""
        d: dict = {"cluster_name": self.cluster_name, "decision": self.decision}
        if self.reason:
            d["reason"] = self.reason
        return d

    @classmethod
    def from_dict(cls, data: dict | BacklogDecision) -> BacklogDecision:
        """Deserialize from persisted plan data, or pass through unchanged."""
        if isinstance(data, cls):
            return data
        return cls(
            cluster_name=data.get("cluster_name", ""),
            decision=data.get("decision", "skip"),  # type: ignore[arg-type]
            reason=data.get("reason", ""),
        )


_BACKLOG_DECISION_RE = re.compile(
    r"-\s*(\S+)\s*->\s*(promote|skip|supersede)\b\s*(.*)",
    re.IGNORECASE,
)


def _iter_backlog_decisions_lines(report: str) -> tuple[bool, list[str]]:
    """Extract lines from the ## Backlog Decisions section of a reflect report."""
    found_section = False
    in_section = False
    lines: list[str] = []
    for raw_line in report.splitlines():
        line = raw_line.strip()
        if re.fullmatch(r"##\s+Backlog Decisions", line, re.IGNORECASE):
            found_section = True
            in_section = True
            continue
        if in_section and re.match(r"##\s+", line):
            break
        if in_section:
            lines.append(line)
    return found_section, lines


def parse_backlog_decisions(report: str) -> list[BacklogDecision]:
    """Parse structured backlog decisions from the ## Backlog Decisions section."""
    _, lines = _iter_backlog_decisions_lines(report)
    decisions: list[BacklogDecision] = []
    for line in lines:
        match = _BACKLOG_DECISION_RE.match(line)
        if not match:
            continue
        cluster_name = match.group(1).strip().strip("`")
        decision_raw = match.group(2).strip().lower()
        reason = match.group(3).strip().strip('"\'')
        if decision_raw in ("promote", "skip", "supersede"):
            decisions.append(BacklogDecision(
                cluster_name=cluster_name,
                decision=decision_raw,  # type: ignore[arg-type]
                reason=reason,
            ))
    return decisions


def validate_backlog_decisions(
    *,
    report: str,
    auto_cluster_names: list[str],
) -> tuple[bool, list[str]]:
    """Warn when auto-clusters exist but no backlog decisions section is found.

    Returns ``(ok, warnings)`` — always ``ok=True`` (non-blocking), but
    populates warnings when backlog decisions are missing or incomplete.
    """
    if not auto_cluster_names:
        return True, []

    found_section, _ = _iter_backlog_decisions_lines(report)
    if not found_section:
        return True, [
            f"Reflect report has {len(auto_cluster_names)} auto-cluster(s) in the backlog "
            "but no `## Backlog Decisions` section. Each auto-cluster should have an "
            "explicit decision: promote, skip (with reason), or supersede."
        ]

    decisions = parse_backlog_decisions(report)
    decided_names = {d.cluster_name for d in decisions}
    missing = [name for name in auto_cluster_names if name not in decided_names]
    if missing:
        missing_str = ", ".join(missing[:10])
        suffix = f" (and {len(missing) - 10} more)" if len(missing) > 10 else ""
        return True, [
            f"Backlog Decisions section is missing decisions for {len(missing)} "
            f"auto-cluster(s): {missing_str}{suffix}"
        ]

    return True, []


__all__ = [
    "BacklogDecision",
    "ReflectDisposition",
    "analyze_reflect_issue_accounting",
    "parse_backlog_decisions",
    "parse_reflect_dispositions",
    "validate_backlog_decisions",
    "validate_reflect_accounting",
]
