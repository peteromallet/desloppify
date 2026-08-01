"""Schema-drift clustering for Python dict literals."""

from __future__ import annotations

import ast
import logging
from collections import defaultdict
from pathlib import Path

from desloppify.base.discovery.paths import get_project_root
from desloppify.base.discovery.source import find_py_files

from .shared import _is_singular_plural, _levenshtein

logger = logging.getLogger(__name__)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _read_python_file(filepath: str) -> str | None:
    try:
        file_path = (
            Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
        )
        return file_path.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug(
            "Skipping unreadable python file %s in schema-drift pass: %s",
            filepath,
            exc,
        )
        return None


def _parse_python_ast(source: str, *, filepath: str) -> ast.AST | None:
    try:
        return ast.parse(source, filename=filepath)
    except SyntaxError as exc:
        logger.debug(
            "Skipping unparseable python file %s in schema-drift pass: %s",
            filepath,
            exc,
        )
        return None


def _extract_literal_keyset(node: ast.Dict) -> frozenset[str] | None:
    if len(node.keys) < 3:
        return None
    if any(key is None for key in node.keys):
        return None
    literal_keys: list[str] = []
    for key in node.keys:
        if key is None:
            continue
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        literal_keys.append(key.value)
    return frozenset(literal_keys)


def _call_context_name(node: ast.Call) -> str:
    """Return a stable callee label for a call containing a dict literal."""

    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return "<dynamic>"


def _literal_comparison_scope(node: ast.Dict, parents: dict[ast.AST, ast.AST]) -> str:
    """Return the drift-comparison scope for a dict literal.

    A dict passed to a named ``*Schema`` constructor declares a validation
    contract, whereas ordinary dict literals commonly carry runtime payloads.
    Keep each schema constructor family out of the generic payload cluster;
    preserve the detector's historical global comparison for every other
    literal.
    """

    parent = parents.get(node)
    if isinstance(parent, ast.Call):
        callee_name = _call_context_name(parent)
        if callee_name.endswith("Schema"):
            return f"schema-constructor:{callee_name}"
    return "generic"


def _collect_schema_literals(files: list[str]) -> list[dict]:
    literals: list[dict] = []
    for filepath in files:
        source = _read_python_file(filepath)
        if source is None:
            continue
        tree = _parse_python_ast(source, filepath=filepath)
        if tree is None:
            continue
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }

        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keyset = _extract_literal_keyset(node)
            if keyset is None:
                continue
            literals.append(
                {
                    "file": filepath,
                    "line": node.lineno,
                    "keys": keyset,
                    "comparison_scope": _literal_comparison_scope(node, parents),
                }
            )
    return literals


def _cluster_by_jaccard(literals: list[dict], *, threshold: float = 0.8) -> list[list[dict]]:
    """Greedy single-linkage clustering by Jaccard similarity threshold."""
    clusters: list[list[dict]] = []
    assigned = [False] * len(literals)

    for index, literal in enumerate(literals):
        if assigned[index]:
            continue
        cluster = [literal]
        assigned[index] = True
        for probe_idx in range(index + 1, len(literals)):
            if assigned[probe_idx]:
                continue
            candidate = literals[probe_idx]
            if candidate.get("comparison_scope", "generic") != literal.get(
                "comparison_scope", "generic"
            ):
                continue
            if any(
                _jaccard(member["keys"], candidate["keys"]) >= threshold
                for member in cluster
            ):
                cluster.append(candidate)
                assigned[probe_idx] = True
        clusters.append(cluster)

    return clusters


def _cluster_key_frequency(cluster: list[dict]) -> dict[str, int]:
    freq: dict[str, int] = defaultdict(int)
    for member in cluster:
        for key in member["keys"]:
            freq[key] += 1
    return freq


def _closest_consensus_key(outlier_key: str, consensus: set[str]) -> str | None:
    for consensus_key in consensus:
        distance = _levenshtein(outlier_key, consensus_key)
        if distance <= 2 or _is_singular_plural(outlier_key, consensus_key):
            return consensus_key
    return None


def _build_schema_drift_issues(clusters: list[list[dict]]) -> list[dict]:
    issues: list[dict] = []
    for cluster in clusters:
        if len(cluster) < 3:
            continue

        key_freq = _cluster_key_frequency(cluster)
        threshold = 0.3 * len(cluster)
        consensus = {key for key, count in key_freq.items() if count >= threshold}

        for member in cluster:
            outlier_keys = member["keys"] - consensus
            for outlier_key in outlier_keys:
                close_match = _closest_consensus_key(outlier_key, consensus)
                present = key_freq[outlier_key]
                tier = 2 if len(cluster) >= 5 else 3
                confidence = "high" if len(cluster) >= 5 else "medium"
                suggestion = f' Did you mean "{close_match}"?' if close_match else ""
                issues.append(
                    {
                        "file": member["file"],
                        "kind": "schema_drift",
                        "key": outlier_key,
                        "line": member["line"],
                        "tier": tier,
                        "confidence": confidence,
                        "summary": (
                            f"Schema drift: {len(cluster) - present}/{len(cluster)} dict literals use different "
                            f'key, but {member["file"]}:{member["line"]} uses "{outlier_key}".{suggestion}'
                        ),
                        "detail": (
                            f'Cluster of {len(cluster)} similar dict literals. Key "{outlier_key}" appears in '
                            f"only {present}. Consensus keys: {sorted(consensus)}"
                        ),
                    }
                )
    return issues


def detect_schema_drift(path: Path) -> tuple[list[dict], int]:
    """Cluster dict literals by key similarity and report outlier keys."""
    files = find_py_files(path)
    all_literals = _collect_schema_literals(files)
    if len(all_literals) < 3:
        return [], len(all_literals)

    clusters = _cluster_by_jaccard(all_literals, threshold=0.8)
    issues = _build_schema_drift_issues(clusters)
    return issues, len(all_literals)
