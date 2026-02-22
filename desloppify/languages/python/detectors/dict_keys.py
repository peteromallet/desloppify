"""Dict key flow analysis — detect dead writes, phantom reads, typos, and schema drift."""

from __future__ import annotations

import ast
import importlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.file_discovery import find_py_files

logger = logging.getLogger(__name__)

# ── Data structures ───────────────────────────────────────


@dataclass
class TrackedDict:
    """A dict variable tracked within a single scope."""

    name: str
    created_line: int
    locally_created: bool
    returned_or_passed: bool = False
    has_dynamic_key: bool = False
    has_star_unpack: bool = False
    writes: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    reads: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    bulk_read: bool = False  # .keys(), .values(), .items(), for x in d


# Variable name patterns that suppress dead-write warnings
_CONFIG_NAMES = {
    "config",
    "settings",
    "defaults",
    "options",
    "kwargs",
    "context",
    "ctx",
    "env",
    "params",
    "metadata",
    "headers",
    "attrs",
    "attributes",
    "props",
    "properties",
}

# Dict method → effect
_READ_METHODS = {"get", "pop", "setdefault", "__getitem__", "__contains__"}
_WRITE_METHODS = {"update", "setdefault", "__setitem__"}
_BULK_READ_METHODS = {"keys", "values", "items", "copy", "__iter__"}


def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def _is_singular_plural(a: str, b: str) -> bool:
    """Check if a and b are singular/plural variants of each other."""
    return (
        a + "s" == b
        or b + "s" == a
        or a + "es" == b
        or b + "es" == a
        or (a.endswith("ies") and a[:-3] + "y" == b)
        or (b.endswith("ies") and b[:-3] + "y" == a)
    )


# ── AST Visitor ───────────────────────────────────────────


def _load_dict_key_visitor():
    module = importlib.import_module(".dict_keys_visitor", package=__package__)
    return module.DictKeyVisitor


def _get_name(node: ast.expr) -> str | None:
    """Extract variable name from a Name or Attribute(self.x) node."""
    if isinstance(node, ast.Name):
        return node.id
    return (
        f"{node.value.id}.{node.attr}"
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        else None
    )


def _get_str_key(node: ast.expr) -> str | None:
    """Extract a string literal from a subscript slice."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _read_and_parse_python_file(filepath: str, *, purpose: str) -> tuple[Path, ast.AST] | None:
    try:
        file_path = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
        source = file_path.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug("Skipping unreadable file during %s scan: %s", purpose, filepath, exc_info=exc)
        return None
    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError as exc:
        logger.debug("Skipping unparsable file during %s scan: %s", purpose, filepath, exc_info=exc)
        return None
    return file_path, tree


# ── Pass 1: Single-scope dict key analysis ────────────────


def detect_dict_key_flow(path: Path) -> tuple[list[dict], int]:
    """Walk all .py files, run DictKeyVisitor. Returns (entries, files_checked)."""
    dict_key_visitor = _load_dict_key_visitor()
    files = find_py_files(path)
    all_findings: list[dict] = []
    all_literals: list[dict] = []

    for filepath in files:
        try:
            p = (
                Path(filepath)
                if Path(filepath).is_absolute()
                else PROJECT_ROOT / filepath
            )
            source = p.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug(
                "Skipping unreadable python file %s in dict-key pass: %s", filepath, exc
            )
            continue

        try:
            tree = ast.parse(source, filename=filepath)
        except SyntaxError as exc:
            logger.debug(
                "Skipping unparseable python file %s in dict-key pass: %s",
                filepath,
                exc,
            )
            continue

        visitor = dict_key_visitor(filepath)
        visitor.visit(tree)
        all_findings.extend(visitor._findings)
        all_literals.extend(visitor._dict_literals)

    return all_findings, len(files)


# ── Pass 2: Schema drift clustering ──────────────────────


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _read_python_file(filepath: str, *, path: Path) -> str | None:
    try:
        file_path = (
            Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
        )
        return file_path.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug(
            "Skipping unreadable python file %s in schema-drift pass: %s", filepath, exc
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
        return None  # Has **spread
    literal_keys: list[str] = []
    for key in node.keys:
        if key is None:
            continue
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        literal_keys.append(key.value)
    return frozenset(literal_keys)


def _collect_schema_literals(path: Path, files: list[str]) -> list[dict]:
    literals: list[dict] = []
    for filepath in files:
        source = _read_python_file(filepath, path=path)
        if source is None:
            continue
        tree = _parse_python_ast(source, filepath=filepath)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keyset = _extract_literal_keyset(node)
            if keyset is None:
                continue
            literals.append({"file": filepath, "line": node.lineno, "keys": keyset})
    return literals


def _cluster_by_jaccard(
    literals: list[dict], *, threshold: float = 0.8
) -> list[list[dict]]:
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


def _build_schema_drift_findings(clusters: list[list[dict]]) -> list[dict]:
    findings: list[dict] = []
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
                findings.append(
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
    return findings


def detect_schema_drift(path: Path) -> tuple[list[dict], int]:
    """Cluster dict literals by key similarity, report outlier keys.

    Returns (entries, literals_checked).
    """
    files = find_py_files(path)
    all_literals = _collect_schema_literals(path, files)

    if len(all_literals) < 3:
        return [], len(all_literals)

    clusters = _cluster_by_jaccard(all_literals, threshold=0.8)
    findings = _build_schema_drift_findings(clusters)

    return findings, len(all_literals)
