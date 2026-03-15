"""Duplicate / near-duplicate function detection via body hashing + difflib similarity.

Output is clustered: N similar functions produce 1 entry (not N^2/2 pairwise entries).
Each entry contains a representative pair for display plus the full cluster membership.
"""

from __future__ import annotations

import difflib
import os
import sys
import time
from typing import TypeAlias, TypedDict

from desloppify.engine.detectors.base import FunctionInfo

PairKey: TypeAlias = tuple[str, str]
MatchedPair: TypeAlias = tuple[int, int, float, str]

_DUPES_CACHE_VERSION = 1
_DUPES_CACHE_MAX_NEAR_PAIRS = 20_000
_DUPES_AUTOJUNK_MIN_LINES = 80


class DuplicateMember(TypedDict):
    file: str
    name: str
    line: int
    loc: int


class DuplicateEntry(TypedDict):
    fn_a: DuplicateMember
    fn_b: DuplicateMember
    similarity: float
    kind: str
    cluster_size: int
    cluster: list[DuplicateMember]


class _CachedFunctionMeta(TypedDict):
    body_hash: str
    loc: int


class _CachedNearPair(TypedDict):
    a: str
    b: str
    similarity: float


def _build_clusters(
    pairs: list[MatchedPair], n: int
) -> list[list[int]]:
    """Union-find clustering from pairwise matches. Returns list of clusters (size >= 2)."""
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
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


def _dupes_debug_settings() -> tuple[bool, int]:
    """Read dupes debug flags from environment."""
    debug = os.getenv("DESLOPPIFY_DUPES_DEBUG", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    try:
        debug_every = max(
            1, int(os.getenv("DESLOPPIFY_DUPES_DEBUG_EVERY", "100") or "100")
        )
    except ValueError:
        debug_every = 100
    return debug, debug_every


def _pair_key(fn_a: FunctionInfo, fn_b: FunctionInfo) -> PairKey:
    """Build a stable pair key for duplicate tracking."""
    return (_function_identity(fn_a), _function_identity(fn_b))


def _function_identity(fn: FunctionInfo) -> str:
    """Build a stable identity token for one function."""
    end_line = getattr(fn, "end_line", None)
    if not isinstance(end_line, int):
        end_line = int(getattr(fn, "line", 0)) + int(getattr(fn, "loc", 0))
    return f"{fn.file}:{fn.name}:{fn.line}:{end_line}"


def _build_function_cache_map(
    functions: list[FunctionInfo],
) -> tuple[dict[str, _CachedFunctionMeta], dict[str, int]]:
    """Build cache metadata and index map for function identities."""
    meta_by_id: dict[str, _CachedFunctionMeta] = {}
    index_by_id: dict[str, int] = {}
    for idx, fn in enumerate(functions):
        func_id = _function_identity(fn)
        meta_by_id[func_id] = {
            "body_hash": fn.body_hash,
            "loc": int(fn.loc),
        }
        index_by_id[func_id] = idx
    return meta_by_id, index_by_id


def _load_cached_near_pairs(
    *,
    cache: dict[str, object],
    threshold: float,
    functions: list[FunctionInfo],
    function_meta: dict[str, _CachedFunctionMeta],
    index_by_id: dict[str, int],
    seen_pairs: set[PairKey],
) -> tuple[list[MatchedPair], set[str] | None]:
    """Return reusable near-duplicate pairs and changed function identities.

    Returns ``([], None)`` when cache is missing/incompatible, signaling that
    near-duplicate pass should run in full mode.
    """
    if cache.get("version") != _DUPES_CACHE_VERSION:
        return [], None

    cached_threshold = cache.get("threshold")
    if not isinstance(cached_threshold, int | float):
        return [], None
    if float(cached_threshold) != float(threshold):
        return [], None

    cached_functions = cache.get("functions")
    cached_near_pairs = cache.get("near_pairs")
    if not isinstance(cached_functions, dict) or not isinstance(cached_near_pairs, list):
        return [], None

    changed_ids: set[str] = set()
    for func_id, meta in function_meta.items():
        previous = cached_functions.get(func_id)
        if not isinstance(previous, dict):
            changed_ids.add(func_id)
            continue
        if previous.get("body_hash") != meta["body_hash"]:
            changed_ids.add(func_id)
            continue
        prev_loc = previous.get("loc")
        if not isinstance(prev_loc, int):
            changed_ids.add(func_id)
            continue
        if prev_loc != meta["loc"]:
            changed_ids.add(func_id)

    reusable_pairs: list[MatchedPair] = []
    for raw_pair in cached_near_pairs:
        if not isinstance(raw_pair, dict):
            continue
        left_id = raw_pair.get("a")
        right_id = raw_pair.get("b")
        similarity = raw_pair.get("similarity")
        if (
            not isinstance(left_id, str)
            or not isinstance(right_id, str)
            or not isinstance(similarity, int | float)
        ):
            continue
        if left_id in changed_ids or right_id in changed_ids:
            continue
        left_idx = index_by_id.get(left_id)
        right_idx = index_by_id.get(right_id)
        if left_idx is None or right_idx is None or left_idx == right_idx:
            continue

        left_fn = functions[left_idx]
        right_fn = functions[right_idx]
        if left_fn.body_hash == right_fn.body_hash:
            continue
        pair_key = _pair_key(left_fn, right_fn)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        reusable_pairs.append((left_idx, right_idx, float(similarity), "near-duplicate"))

    return reusable_pairs, changed_ids


def _store_dupes_cache(
    *,
    cache: dict[str, object],
    threshold: float,
    functions: list[FunctionInfo],
    function_meta: dict[str, _CachedFunctionMeta],
    pairs: list[MatchedPair],
) -> None:
    """Persist near-duplicate cache payload for reuse on next scan."""
    near_pairs: list[_CachedNearPair] = []
    for left_idx, right_idx, similarity, kind in pairs:
        if kind != "near-duplicate":
            continue
        left_id = _function_identity(functions[left_idx])
        right_id = _function_identity(functions[right_idx])
        near_pairs.append(
            {
                "a": left_id,
                "b": right_id,
                "similarity": round(float(similarity), 6),
            }
        )

    near_pairs.sort(key=lambda pair: (-pair["similarity"], pair["a"], pair["b"]))
    if len(near_pairs) > _DUPES_CACHE_MAX_NEAR_PAIRS:
        near_pairs = near_pairs[:_DUPES_CACHE_MAX_NEAR_PAIRS]

    cache.clear()
    cache.update(
        {
            "version": _DUPES_CACHE_VERSION,
            "threshold": float(threshold),
            "functions": function_meta,
            "near_pairs": near_pairs,
        }
    )


def _collect_exact_duplicate_pairs(
    functions: list[FunctionInfo],
    seen_pairs: set[PairKey],
) -> list[MatchedPair]:
    """Collect exact duplicate pairs (same normalized body hash)."""
    by_hash: dict[str, list[int]] = {}
    for idx, fn in enumerate(functions):
        by_hash.setdefault(fn.body_hash, []).append(idx)

    exact_pairs: list[MatchedPair] = []
    for idxs in by_hash.values():
        if len(idxs) < 2:
            continue
        for i_pos in range(len(idxs)):
            for j_pos in range(i_pos + 1, len(idxs)):
                left_idx = idxs[i_pos]
                right_idx = idxs[j_pos]
                pair_key = _pair_key(functions[left_idx], functions[right_idx])
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                exact_pairs.append((left_idx, right_idx, 1.0, "exact"))
    return exact_pairs


def _collect_near_duplicate_pairs(
    functions: list[FunctionInfo],
    threshold: float,
    *,
    seen_pairs: set[PairKey],
    active_indices: set[int] | None,
    debug: bool,
    debug_every: int,
) -> list[MatchedPair]:
    """Collect near-duplicate pairs using SequenceMatcher with pruning."""
    if active_indices is not None and not active_indices:
        return []
    large_idx = [(idx, fn) for idx, fn in enumerate(functions) if fn.loc >= 15]
    large_idx.sort(key=lambda item: item[1].loc)
    normalized_lines = [fn.normalized.splitlines() for fn in functions]
    normalized_line_counts = [len(lines) for lines in normalized_lines]

    near_pairs: list[MatchedPair] = []
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
        idx_a, fn_a = large_idx[i_pos]
        for j_pos in range(i_pos + 1, len(large_idx)):
            idx_b, fn_b = large_idx[j_pos]
            if fn_b.loc > fn_a.loc * 1.5:
                break
            near_candidates += 1

            pair_key = _pair_key(fn_a, fn_b)
            if pair_key in seen_pairs or fn_a.body_hash == fn_b.body_hash:
                continue
            if active_indices is not None:
                if idx_a not in active_indices and idx_b not in active_indices:
                    continue

            # ratio = 2*M/(len_a+len_b), with M <= min(len_a, len_b)
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
                autojunk=len_a >= _DUPES_AUTOJUNK_MIN_LINES and len_b >= _DUPES_AUTOJUNK_MIN_LINES,
            )
            if matcher.real_quick_ratio() < threshold:
                continue
            if matcher.quick_ratio() < threshold:
                continue

            near_ratio_calls += 1
            ratio = matcher.ratio()
            if ratio >= threshold:
                seen_pairs.add(pair_key)
                near_pairs.append((idx_a, idx_b, ratio, "near-duplicate"))

        if debug and i_pos and i_pos % debug_every == 0:
            elapsed = time.perf_counter() - near_start
            print(
                f"[dupes] progress i={i_pos}/{len(large_idx)} "
                f"candidate_pairs={near_candidates} ratio_calls={near_ratio_calls} "
                f"matches={len(near_pairs)} elapsed={elapsed:.2f}s",
                file=sys.stderr,
            )

    if debug:
        elapsed = time.perf_counter() - near_start
        print(
            f"[dupes] done near pass: candidate_pairs={near_candidates} "
            f"ratio_calls={near_ratio_calls} pruned_by_length={near_pruned_by_length} "
            f"matches={len(near_pairs)} elapsed={elapsed:.2f}s",
            file=sys.stderr,
        )

    return near_pairs


def _build_duplicate_entries(
    functions: list[FunctionInfo],
    pairs: list[MatchedPair],
    clusters: list[list[int]],
) -> list[DuplicateEntry]:
    """Build cluster entries from matched duplicate pairs."""
    pair_lookup: dict[int, dict[int, tuple[float, str]]] = {}
    for i, j, similarity, kind in pairs:
        pair_lookup.setdefault(i, {})[j] = (similarity, kind)
        pair_lookup.setdefault(j, {})[i] = (similarity, kind)

    entries: list[DuplicateEntry] = []
    for cluster in clusters:
        best_similarity = 0.0
        best_kind = "near-duplicate"
        best_a = best_b = cluster[0]
        for left in cluster:
            for right, (similarity, kind) in pair_lookup.get(left, {}).items():
                if right in cluster and similarity > best_similarity:
                    best_similarity = similarity
                    best_kind = kind
                    best_a, best_b = left, right

        fn_a, fn_b = functions[best_a], functions[best_b]
        members = [
            {
                "file": functions[idx].file,
                "name": functions[idx].name,
                "line": functions[idx].line,
                "loc": functions[idx].loc,
            }
            for idx in cluster
        ]
        entries.append(
            {
                "fn_a": {
                    "file": fn_a.file,
                    "name": fn_a.name,
                    "line": fn_a.line,
                    "loc": fn_a.loc,
                },
                "fn_b": {
                    "file": fn_b.file,
                    "name": fn_b.name,
                    "line": fn_b.line,
                    "loc": fn_b.loc,
                },
                "similarity": round(best_similarity, 3),
                "kind": best_kind,
                "cluster_size": len(cluster),
                "cluster": members,
            }
        )
    return entries


def detect_duplicates(
    functions: list[FunctionInfo],
    threshold: float = 0.9,
    *,
    cache: dict[str, object] | None = None,
) -> tuple[list[DuplicateEntry], int]:
    """Find duplicate or near-duplicate functions clustered by similarity."""
    if not functions:
        return [], 0
    debug, debug_every = _dupes_debug_settings()
    seen_pairs: set[PairKey] = set()

    pairs = _collect_exact_duplicate_pairs(functions, seen_pairs)
    function_meta, index_by_id = _build_function_cache_map(functions)
    active_indices: set[int] | None = None
    if isinstance(cache, dict):
        cached_pairs, changed_ids = _load_cached_near_pairs(
            cache=cache,
            threshold=threshold,
            functions=functions,
            function_meta=function_meta,
            index_by_id=index_by_id,
            seen_pairs=seen_pairs,
        )
        pairs.extend(cached_pairs)
        if changed_ids is not None:
            active_indices = {
                index_by_id[func_id]
                for func_id in changed_ids
                if func_id in index_by_id
            }

    pairs.extend(
        _collect_near_duplicate_pairs(
            functions,
            threshold,
            seen_pairs=seen_pairs,
            active_indices=active_indices,
            debug=debug,
            debug_every=debug_every,
        )
    )

    clusters = _build_clusters(pairs, len(functions))
    entries = _build_duplicate_entries(functions, pairs, clusters)
    if isinstance(cache, dict):
        _store_dupes_cache(
            cache=cache,
            threshold=threshold,
            functions=functions,
            function_meta=function_meta,
            pairs=pairs,
        )
    return sorted(entries, key=lambda e: (-e["similarity"], -e["cluster_size"])), len(
        functions
    )
