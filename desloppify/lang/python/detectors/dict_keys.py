"""Dict key flow analysis — detect dead writes, phantom reads, typos, and schema drift."""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ....utils import PROJECT_ROOT, find_py_files

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
_CONFIG_NAMES = {"config", "settings", "defaults", "options", "kwargs",
                 "context", "ctx", "env", "params", "metadata", "headers",
                 "attrs", "attributes", "props", "properties"}

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
    if a + "s" == b or b + "s" == a:
        return True
    if a + "es" == b or b + "es" == a:
        return True
    if a.endswith("ies") and a[:-3] + "y" == b:
        return True
    if b.endswith("ies") and b[:-3] + "y" == a:
        return True
    return False


# ── AST Visitor ───────────────────────────────────────────

def _get_name(node: ast.expr) -> str | None:
    """Extract variable name from a Name or Attribute(self.x) node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return None


def _get_str_key(node: ast.expr) -> str | None:
    """Extract a string literal from a subscript slice."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


# ── Pass 1: Single-scope dict key analysis ────────────────

def detect_dict_key_flow(path: Path) -> tuple[list[dict], int]:
    """Walk all .py files, run DictKeyVisitor. Returns (entries, files_checked)."""
    from .dict_keys_visitor import DictKeyVisitor
    files = find_py_files(path)
    all_findings: list[dict] = []
    all_literals: list[dict] = []

    for filepath in files:
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
            source = p.read_text()
        except (OSError, UnicodeDecodeError):
            continue

        try:
            tree = ast.parse(source, filename=filepath)
        except SyntaxError:
            continue

        visitor = DictKeyVisitor(filepath)
        visitor.visit(tree)
        all_findings.extend(visitor._findings)
        all_literals.extend(visitor._dict_literals)

    return all_findings, len(files)


# ── Pass 2: Schema drift clustering ──────────────────────

def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def detect_schema_drift(path: Path) -> tuple[list[dict], int]:
    """Cluster dict literals by key similarity, report outlier keys.

    Returns (entries, literals_checked).
    """
    files = find_py_files(path)
    all_literals: list[dict] = []

    for filepath in files:
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
            source = p.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tree = ast.parse(source, filename=filepath)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            if len(node.keys) < 3:
                continue
            if not all(isinstance(k, ast.Constant) and isinstance(k.value, str)
                       for k in node.keys if k is not None):
                continue
            if any(k is None for k in node.keys):
                continue  # Has **spread
            keys = frozenset(k.value for k in node.keys if isinstance(k, ast.Constant))
            all_literals.append({
                "file": filepath, "line": node.lineno, "keys": keys,
            })

    if len(all_literals) < 3:
        return [], len(all_literals)

    # Greedy single-linkage clustering with Jaccard >= 0.8
    clusters: list[list[dict]] = []
    assigned = [False] * len(all_literals)

    for i, lit in enumerate(all_literals):
        if assigned[i]:
            continue
        cluster = [lit]
        assigned[i] = True
        for j in range(i + 1, len(all_literals)):
            if assigned[j]:
                continue
            # Check similarity against any member in the cluster
            for member in cluster:
                if _jaccard(lit["keys"], all_literals[j]["keys"]) >= 0.8:
                    cluster.append(all_literals[j])
                    assigned[j] = True
                    break
        clusters.append(cluster)

    # Report outlier keys within clusters of size >= 3
    findings: list[dict] = []
    for cluster in clusters:
        if len(cluster) < 3:
            continue

        # Build key frequency
        key_freq: dict[str, int] = defaultdict(int)
        for member in cluster:
            for k in member["keys"]:
                key_freq[k] += 1

        # Find consensus keys and outliers
        threshold = 0.3 * len(cluster)
        consensus = {k for k, v in key_freq.items() if v >= threshold}

        for member in cluster:
            outlier_keys = member["keys"] - consensus
            for ok in outlier_keys:
                # Check if it's close to a consensus key (likely typo)
                close_match = None
                for ck in consensus:
                    dist = _levenshtein(ok, ck)
                    if dist <= 2 or _is_singular_plural(ok, ck):
                        close_match = ck
                        break

                present = key_freq[ok]
                tier = 2 if len(cluster) >= 5 else 3
                confidence = "high" if len(cluster) >= 5 else "medium"

                suggestion = f' Did you mean "{close_match}"?' if close_match else ""
                findings.append({
                    "file": member["file"], "kind": "schema_drift",
                    "key": ok, "line": member["line"],
                    "tier": tier, "confidence": confidence,
                    "summary": (f'Schema drift: {len(cluster) - present}/{len(cluster)} '
                                f'dict literals use different key, but '
                                f'{member["file"]}:{member["line"]} uses "{ok}".{suggestion}'),
                    "detail": (f"Cluster of {len(cluster)} similar dict literals. "
                               f'Key "{ok}" appears in only {present}. '
                               f"Consensus keys: {sorted(consensus)}"),
                })

    return findings, len(all_literals)
