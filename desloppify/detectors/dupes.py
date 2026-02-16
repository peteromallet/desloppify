"""Duplicate / near-duplicate function detection via body hashing + difflib similarity.

Output is clustered: N similar functions produce 1 entry (not N^2/2 pairwise entries).
Each entry contains a representative pair for display plus the full cluster membership.
"""

import difflib
import os
import sys
import time


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
    debug = os.getenv("DESLOPPIFY_DUPES_DEBUG", "").lower() in {"1", "true", "yes", "on"}
    try:
        debug_every = max(1, int(os.getenv("DESLOPPIFY_DUPES_DEBUG_EVERY", "100") or "100"))
    except ValueError:
        debug_every = 100

    # Phase 1: Exact duplicates (same hash)
    by_hash: dict[str, list[int]] = {}
    for idx, fn in enumerate(functions):
        by_hash.setdefault(fn.body_hash, []).append(idx)

    pairs: list[tuple[int, int, float, str]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for h, idxs in by_hash.items():
        if len(idxs) > 1:
            for i_pos in range(len(idxs)):
                for j_pos in range(i_pos + 1, len(idxs)):
                    fi, fj = functions[idxs[i_pos]], functions[idxs[j_pos]]
                    pair_key = (f"{fi.file}:{fi.name}", f"{fj.file}:{fj.name}")
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        pairs.append((idxs[i_pos], idxs[j_pos], 1.0, "exact"))

    # Phase 2: Near-duplicates (difflib similarity on functions >= 15 LOC)
    large_idx = [(idx, fn) for idx, fn in enumerate(functions) if fn.loc >= 15]
    large_idx.sort(key=lambda x: x[1].loc)
    normalized_lines = [fn.normalized.splitlines() for fn in functions]
    normalized_line_counts = [len(lines) for lines in normalized_lines]

    near_candidates = 0
    near_ratio_calls = 0
    near_pruned_by_length = 0
    near_start = time.perf_counter()

    if debug:
        print(
            f"[dupes] start near pass: total_functions={n} "
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
            pair_key = (f"{fa.file}:{fa.name}", f"{fb.file}:{fb.name}")
            if pair_key in seen_pairs:
                continue
            if fa.body_hash == fb.body_hash:
                continue

            # Upper bound on SequenceMatcher.ratio() based on sequence lengths:
            # ratio = 2*M/(len_a+len_b) and M <= min(len_a, len_b).
            len_a = normalized_line_counts[idx_a]
            len_b = normalized_line_counts[idx_b]
            if not len_a or not len_b:
                near_pruned_by_length += 1
                continue
            max_possible = (2 * min(len_a, len_b)) / (len_a + len_b)
            if max_possible < threshold:
                near_pruned_by_length += 1
                continue

            matcher = difflib.SequenceMatcher(
                None,
                normalized_lines[idx_a],
                normalized_lines[idx_b],
                autojunk=False,
            )
            # Cheap similarity bounds before full ratio().
            if matcher.real_quick_ratio() < threshold:
                continue
            if matcher.quick_ratio() < threshold:
                continue

            near_ratio_calls += 1
            ratio = matcher.ratio()
            if ratio >= threshold:
                seen_pairs.add(pair_key)
                pairs.append((idx_a, idx_b, ratio, "near-duplicate"))

        if debug and i_pos and i_pos % debug_every == 0:
            elapsed = time.perf_counter() - near_start
            print(
                f"[dupes] progress i={i_pos}/{len(large_idx)} "
                f"candidate_pairs={near_candidates} ratio_calls={near_ratio_calls} "
                f"matches={len(pairs)} elapsed={elapsed:.2f}s",
                file=sys.stderr,
            )

    if debug:
        elapsed = time.perf_counter() - near_start
        print(
            f"[dupes] done near pass: candidate_pairs={near_candidates} "
            f"ratio_calls={near_ratio_calls} pruned_by_length={near_pruned_by_length} "
            f"matches={len(pairs)} elapsed={elapsed:.2f}s",
            file=sys.stderr,
        )

    # Cluster: group connected functions so N similar → 1 entry (not N^2/2)
    clusters = _build_clusters(pairs, n)

    # Build a lookup for best pair per cluster (highest similarity) for display
    pair_lookup: dict[int, dict[int, tuple[float, str]]] = {}
    for i, j, sim, kind in pairs:
        pair_lookup.setdefault(i, {})[j] = (sim, kind)
        pair_lookup.setdefault(j, {})[i] = (sim, kind)

    entries = []
    for cluster in clusters:
        # Find the best (highest similarity) pair in this cluster for the summary
        best_sim = 0.0
        best_kind = "near-duplicate"
        best_a = best_b = cluster[0]
        for ci in cluster:
            for cj, (sim, kind) in pair_lookup.get(ci, {}).items():
                if cj in cluster and sim > best_sim:
                    best_sim = sim
                    best_kind = kind
                    best_a, best_b = ci, cj

        fa, fb = functions[best_a], functions[best_b]
        members = [{"file": functions[c].file, "name": functions[c].name,
                     "line": functions[c].line, "loc": functions[c].loc}
                    for c in cluster]
        entries.append({
            "fn_a": {"file": fa.file, "name": fa.name,
                     "line": fa.line, "loc": fa.loc},
            "fn_b": {"file": fb.file, "name": fb.name,
                     "line": fb.line, "loc": fb.loc},
            "similarity": round(best_sim, 3),
            "kind": best_kind,
            "cluster_size": len(cluster),
            "cluster": members,
        })

    return sorted(entries, key=lambda e: (-e["similarity"], -e["cluster_size"])), n
