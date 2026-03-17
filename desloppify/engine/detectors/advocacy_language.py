"""Advocacy language detector — finds speciesist language in code and docs.

Loads canonical YAML rules from advocacy_rules/ and applies regex patterns
to file contents. Context suppression rules reduce false positives for
technical terms, proper nouns, and quotations.

Rules source: Open-Paws/project-compassionate-code canonical dictionaries.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Extensions to scan beyond what the language module provides.
_EXTRA_EXTENSIONS = frozenset({".md", ".txt", ".rst", ".mdx", ".markdown"})

# Severity → (desloppify tier, desloppify confidence)
_SEVERITY_MAP: dict[str, tuple[int, str]] = {
    "critical": (2, "high"),
    "high": (2, "high"),
    "medium": (3, "medium"),
    "low": (4, "low"),
    "info": (4, "low"),
}


@dataclass
class _Rule:
    term: str
    severity: str
    pattern: re.Pattern[str]
    alternatives: list[str]
    description: str
    category: str
    tier: int
    confidence: str


@dataclass
class _ContextRule:
    name: str
    pattern: re.Pattern[str]


@dataclass
class _RuleSet:
    rules: list[_Rule] = field(default_factory=list)
    suppress_rules: list[_ContextRule] = field(default_factory=list)
    downgrade_rules: list[_ContextRule] = field(default_factory=list)


_cached_ruleset: _RuleSet | None = None


def _rules_dir() -> Path:
    return Path(__file__).parent / "advocacy_rules"


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file. Uses PyYAML if available, falls back to basic parsing."""
    try:
        import yaml

        with open(path) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        # Minimal fallback: the YAML files are simple enough for basic parsing
        # but we really want PyYAML — warn and return empty.
        logger.warning(
            "PyYAML not installed — advocacy language rules will not load. "
            "Install with: pip install PyYAML"
        )
        return {}


def _load_ruleset() -> _RuleSet:
    global _cached_ruleset
    if _cached_ruleset is not None:
        return _cached_ruleset

    rules_dir = _rules_dir()
    rs = _RuleSet()

    # Load rule files
    rule_files = [
        "idioms.yaml",
        "metaphors.yaml",
        "insults.yaml",
        "process-language.yaml",
        "terminology.yaml",
    ]
    for filename in rule_files:
        path = rules_dir / filename
        if not path.exists():
            logger.warning("Advocacy rule file not found: %s", path)
            continue
        data = _load_yaml(path)
        category = data.get("category", filename.replace(".yaml", ""))
        for entry in data.get("entries", []):
            severity = entry.get("severity", "medium")
            tier, confidence = _SEVERITY_MAP.get(severity, (3, "medium"))
            try:
                compiled = re.compile(entry["pattern"], re.IGNORECASE)
            except re.error as e:
                logger.warning("Bad regex in %s for '%s': %s", filename, entry.get("term"), e)
                continue
            rs.rules.append(
                _Rule(
                    term=entry.get("term", ""),
                    severity=severity,
                    pattern=compiled,
                    alternatives=entry.get("alternatives", []),
                    description=entry.get("description", ""),
                    category=category,
                    tier=tier,
                    confidence=confidence,
                )
            )

    # Load context suppression rules (technical-terms, proper-nouns)
    context_dir = rules_dir / "context-rules"
    for filename in ("technical-terms.yaml", "proper-nouns.yaml"):
        path = context_dir / filename
        if not path.exists():
            continue
        data = _load_yaml(path)
        for rule in data.get("rules", []):
            try:
                compiled = re.compile(rule["pattern"], re.IGNORECASE)
            except re.error:
                continue
            rs.suppress_rules.append(
                _ContextRule(name=rule.get("name", ""), pattern=compiled)
            )

    # Load quotation downgrade rules (reduce confidence, don't suppress)
    quote_path = context_dir / "quotations.yaml"
    if quote_path.exists():
        data = _load_yaml(quote_path)
        for rule in data.get("rules", []):
            try:
                compiled = re.compile(rule["pattern"], re.IGNORECASE)
            except re.error:
                continue
            rs.downgrade_rules.append(
                _ContextRule(name=rule.get("name", ""), pattern=compiled)
            )

    _cached_ruleset = rs
    logger.debug(
        "Loaded %d advocacy rules, %d suppress rules, %d downgrade rules",
        len(rs.rules),
        len(rs.suppress_rules),
        len(rs.downgrade_rules),
    )
    return rs


def _should_suppress(line: str, suppress_rules: list[_ContextRule]) -> bool:
    """Check if a line matches any context suppression rule."""
    for rule in suppress_rules:
        if rule.pattern.search(line):
            return True
    return False


def _should_downgrade(line: str, downgrade_rules: list[_ContextRule]) -> bool:
    """Check if a line matches any quotation downgrade rule."""
    for rule in downgrade_rules:
        if rule.pattern.search(line):
            return True
    return False


def _find_files(path: Path, lang_extensions: frozenset[str] | None = None) -> list[str]:
    """Find text files to scan under the given path."""
    extensions = set(_EXTRA_EXTENSIONS)
    if lang_extensions:
        extensions |= set(lang_extensions)

    if path.is_file():
        return [str(path)]

    files = []
    for root, dirs, filenames in os.walk(path):
        # Skip common non-content directories
        dirs[:] = [
            d for d in dirs
            if d not in {
                "node_modules", ".git", "dist", "build", ".next",
                "__pycache__", ".mypy_cache", ".pytest_cache", "vendor",
                ".desloppify", ".venv", "venv",
            }
        ]
        for name in filenames:
            if any(name.endswith(ext) for ext in extensions):
                files.append(os.path.join(root, name))
    return files


def detect_advocacy_language(
    path: Path,
    lang_extensions: frozenset[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Detect speciesist language patterns in files under path.

    Returns (entries, potentials) where entries are DetectorEntry-shaped dicts
    and potentials maps detector name to file count.
    """
    rs = _load_ruleset()
    if not rs.rules:
        return [], {"advocacy_language": 0}

    files = _find_files(path, lang_extensions)
    entries: list[dict[str, Any]] = []

    for filepath in files:
        try:
            with open(filepath, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue

        for lineno, line in enumerate(lines, start=1):
            for rule in rs.rules:
                if not rule.pattern.search(line):
                    continue

                # Apply context suppression
                if _should_suppress(line, rs.suppress_rules):
                    continue

                # Determine confidence — downgrade if in quotation context
                confidence = rule.confidence
                if _should_downgrade(line, rs.downgrade_rules):
                    confidence = "low"

                alt_text = rule.alternatives[0] if rule.alternatives else "a non-violent alternative"
                entries.append({
                    "file": filepath,
                    "line": lineno,
                    "tier": rule.tier,
                    "confidence": confidence,
                    "summary": (
                        f'"{rule.term}" → use "{alt_text}" instead '
                        f"({rule.category})"
                    ),
                    "name": rule.term,
                    "detail": {
                        "term": rule.term,
                        "alternatives": rule.alternatives,
                        "severity": rule.severity,
                        "category": rule.category,
                        "content": line.strip()[:200],
                    },
                })

    return entries, {"advocacy_language": len(files)}
