"""Duplicate / near-duplicate function detection via body hashing + difflib similarity.

Output is clustered: N similar functions produce 1 entry (not N^2/2 pairwise entries).
Each entry contains a representative pair for display plus the full cluster membership.
"""

import difflib
import os
import sys
import time


def _pair_key(fn_a, fn_b) -> tuple[str, str]:
    return (f"{fn_a.file}:{fn_a.name}", f"{fn_b.file}:{fn_b.name}")


def _resolve_debug_flags() -> tuple[bool, int]:
    debug = os.getenv("DESLOPPIFY_DUPES_DEBUG", "").lower() in {"1", "true", "yes", "on"}
    try:
        debug_every = max(1, int(os.getenv("DESLOPPIFY_DUPES_DEBUG_EVERY", "100") or "100"))
    except ValueError:
        debug_every = 100
    return debug, debug_every


def _collect_exact_pairs(functions) -> tuple[list[tuple[int, int, float, str]], set[tuple[str, str]]]:
    """Collect exact duplicate function pairs via body hash grouping."""
    by_hash: dict[str, list[int]] = {}
    for idx, fn in enumerate(functions):
        by_hash.setdefault(fn.body_hash, []).append(idx)

    pairs: list[tuple[int, int, float, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for idxs in by_hash.values():
        if len(idxs) <= 1:
            continue
        for i_pos in range(len(idxs)):
            for j_pos in range(i_pos + 1, len(idxs)):
                fi = functions[idxs[i_pos]]
                fj = functions[idxs[j_pos]]
                key = _pair_key(fi, fj)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                pairs.append((idxs[i_pos], idxs[j_pos], 1.0, "exact"))
    return pairs, seen_pairs


def _prepare_near_pass(functions) -> tuple[list[tuple[int, object]], list[list[str]], list[int]]:
    """Prepare sorted candidate indices and normalized line caches for near pass."""
    large_idx = [(idx, fn) for idx, fn in enumerate(functions) if fn.loc >= 15]
    large_idx.sort(key=lambda x: x[1].loc)
    normalized_lines = [fn.normalized.splitlines() for fn in functions]
    normalized_line_counts = [len(lines) for lines in normalized_lines]
    return large_idx, normalized_lines, normalized_line_counts


def _log_near_progress(
    *,
    debug: bool,
    i_pos: int,
    total: int,
    debug_every: int,
    near_candidates: int,
    near_ratio_calls: int,
    pair_count: int,
    near_start: float,
) -> None:
    if not debug:
        return
    if i_pos and i_pos % debug_every == 0:
        elapsed = time.perf_counter() - near_start
        print(
            f"[dupes] progress i={i_pos}/{total} "
            f"candidate_pairs={near_candidates} ratio_calls={near_ratio_calls} "
            f"matches={pair_count} elapsed={elapsed:.2f}s",
            file=sys.stderr,
        )


def _near_pair_is_possible(
    *,
    len_a: int,
    len_b: int,
    threshold: float,
) -> bool:
    if not len_a or not len_b:
        return False
    max_possible = (2 * min(len_a, len_b)) / (len_a + len_b)
    return max_possible >= threshold


def _run_near_pass(
    functions,
    threshold: float,
    *,
    large_idx: list[tuple[int, object]],
    normalized_lines: list[list[str]],
    normalized_line_counts: list[int],
    pairs: list[tuple[int, int, float, str]],
    seen_pairs: set[tuple[str, str]],
    debug: bool,
    debug_every: int,
) -> None:
    near_candidates = 0
    near_ratio_calls = 0
    near_pruned_by_length = 0
    near_start = time.perf_counter()

    if debug:
        print(
            f"[dupes] start near pass: total_functions={len(functions)} "
            f"candidates_by_loc={len(large_idx)} threshold={threshold:.2f}",
            file=sys.stderr,
        )

    for i_pos in range(len(large_idx)):
        for j_pos in range(i_pos + 1, len(large_idx)):
            idx_a, fa = large_idx[i_pos]
            idx_b, fb = large_idx[j_pos]
            if fb.loc > fa.loc * 1.5:
                break
            near_candidates += 1

            key = _pair_key(fa, fb)
            if key in seen_pairs:
                continue
            if fa.body_hash == fb.body_hash:
                continue

            len_a = normalized_line_counts[idx_a]
            len_b = normalized_line_counts[idx_b]
            if not _near_pair_is_possible(len_a=len_a, len_b=len_b, threshold=threshold):
                near_pruned_by_length += 1
                continue

            matcher = difflib.SequenceMatcher(
                None,
                normalized_lines[idx_a],
                normalized_lines[idx_b],
                autojunk=False,
            )
            if matcher.real_quick_ratio() < threshold:
                continue
            if matcher.quick_ratio() < threshold:
                continue

            near_ratio_calls += 1
            ratio = matcher.ratio()
            if ratio >= threshold:
                seen_pairs.add(key)
                pairs.append((idx_a, idx_b, ratio, "near-duplicate"))

        _log_near_progress(
            debug=debug,
            i_pos=i_pos,
            total=len(large_idx),
            debug_every=debug_every,
            near_candidates=near_candidates,
            near_ratio_calls=near_ratio_calls,
            pair_count=len(pairs),
            near_start=near_start,
        )

    if debug:
        elapsed = time.perf_counter() - near_start
        print(
            f"[dupes] done near pass: candidate_pairs={near_candidates} "
            f"ratio_calls={near_ratio_calls} pruned_by_length={near_pruned_by_length} "
            f"matches={len(pairs)} elapsed={elapsed:.2f}s",
            file=sys.stderr,
        )


def _build_entries_from_clusters(
    functions,
    pairs: list[tuple[int, int, float, str]],
    clusters: list[list[int]],
) -> list[dict]:
    """Build report entries from connected duplicate clusters."""
    pair_lookup: dict[int, dict[int, tuple[float, str]]] = {}
    for i, j, sim, kind in pairs:
        pair_lookup.setdefault(i, {})[j] = (sim, kind)
        pair_lookup.setdefault(j, {})[i] = (sim, kind)

    entries = []
    for cluster in clusters:
        best_sim = 0.0
        best_kind = "near-duplicate"
        best_a = best_b = cluster[0]
        for ci in cluster:
            for cj, (sim, kind) in pair_lookup.get(ci, {}).items():
                if cj in cluster and sim > best_sim:
                    best_sim = sim
                    best_kind = kind
                    best_a, best_b = ci, cj

        fa = functions[best_a]
        fb = functions[best_b]
        members = [
            {
                "file": functions[c].file,
                "name": functions[c].name,
                "line": functions[c].line,
                "loc": functions[c].loc,
            }
            for c in cluster
        ]
        entries.append(
            {
                "fn_a": {"file": fa.file, "name": fa.name, "line": fa.line, "loc": fa.loc},
                "fn_b": {"file": fb.file, "name": fb.name, "line": fb.line, "loc": fb.loc},
                "similarity": round(best_sim, 3),
                "kind": best_kind,
                "cluster_size": len(cluster),
                "cluster": members,
            }
        )
    return entries


def _build_clusters(pairs: list[tuple[int, int, float, str]],
                    n: int) -> list[list[int]]:
    """Union-find clustering from pairwise matches. Returns list of clusters (size >= 2)."""
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, j, _, _ in pairs:
        union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        r = find(i)
        clusters.setdefault(r, []).append(i)
    return [c for c in clusters.values() if len(c) >= 2]


def detect_duplicates(functions, threshold: float = 0.9) -> tuple[list[dict], int]:
    """Find duplicate/near-duplicate functions, clustered by similarity.

    Args:
        functions: list of FunctionInfo objects with .file, .name, .line, .loc,
                   .normalized, .body_hash attrs.
        threshold: similarity threshold for near-duplicates (default 0.9).

    Returns:
        (entries, total_functions) where each entry represents a cluster of
        similar functions, not a single pair.
    """
    n = len(functions)
    if not functions:
        return [], 0
    debug, debug_every = _resolve_debug_flags()
    pairs, seen_pairs = _collect_exact_pairs(functions)
    large_idx, normalized_lines, normalized_line_counts = _prepare_near_pass(functions)
    _run_near_pass(
        functions,
        threshold,
        large_idx=large_idx,
        normalized_lines=normalized_lines,
        normalized_line_counts=normalized_line_counts,
        pairs=pairs,
        seen_pairs=seen_pairs,
        debug=debug,
        debug_every=debug_every,
    )

    clusters = _build_clusters(pairs, n)
    entries = _build_entries_from_clusters(functions, pairs, clusters)

    return sorted(entries, key=lambda e: (-e["similarity"], -e["cluster_size"])), n
