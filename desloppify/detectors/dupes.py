"""Duplicate / near-duplicate function detection via body hashing + difflib similarity."""

import difflib


def detect_duplicates(functions, threshold: float = 0.8) -> tuple[list[dict], int]:
    """Find duplicate/near-duplicate functions.

    Args:
        functions: list of FunctionInfo objects with .file, .name, .line, .loc,
                   .normalized, .body_hash attrs.
        threshold: similarity threshold for near-duplicates.

    Returns:
        (entries, total_pairs_checked)
    """
    n = len(functions)
    total_pairs = n * (n - 1) // 2 if n > 1 else 0
    if not functions:
        return [], 0

    # Phase 1: Exact duplicates (same hash)
    by_hash: dict[str, list] = {}
    for fn in functions:
        by_hash.setdefault(fn.body_hash, []).append(fn)

    entries = []
    seen_pairs = set()

    for h, fns in by_hash.items():
        if len(fns) > 1:
            for i in range(len(fns)):
                for j in range(i + 1, len(fns)):
                    pair_key = (f"{fns[i].file}:{fns[i].name}",
                                f"{fns[j].file}:{fns[j].name}")
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)
                    entries.append({
                        "fn_a": {"file": fns[i].file, "name": fns[i].name,
                                 "line": fns[i].line, "loc": fns[i].loc},
                        "fn_b": {"file": fns[j].file, "name": fns[j].name,
                                 "line": fns[j].line, "loc": fns[j].loc},
                        "similarity": 1.0,
                        "kind": "exact",
                    })

    # Phase 2: Near-duplicates (difflib similarity on functions >= 10 LOC)
    large_fns = [fn for fn in functions if fn.loc >= 10]
    large_fns.sort(key=lambda f: f.loc)

    for i in range(len(large_fns)):
        for j in range(i + 1, len(large_fns)):
            fa, fb = large_fns[i], large_fns[j]
            pair_key = (f"{fa.file}:{fa.name}", f"{fb.file}:{fb.name}")
            if pair_key in seen_pairs:
                continue
            if fb.loc > fa.loc * 1.5:
                break
            if fa.body_hash == fb.body_hash:
                continue

            ratio = difflib.SequenceMatcher(None, fa.normalized, fb.normalized).ratio()
            if ratio >= threshold:
                seen_pairs.add(pair_key)
                entries.append({
                    "fn_a": {"file": fa.file, "name": fa.name,
                             "line": fa.line, "loc": fa.loc},
                    "fn_b": {"file": fb.file, "name": fb.name,
                             "line": fb.line, "loc": fb.loc},
                    "similarity": round(ratio, 3),
                    "kind": "near-duplicate",
                })

    return sorted(entries, key=lambda e: -e["similarity"]), total_pairs
