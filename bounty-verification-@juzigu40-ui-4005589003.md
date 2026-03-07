# Bounty Verification: S154 @juzigu40-ui — Tri-State Full-Sweep Logic Suppresses Coverage Debt

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4005589003
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `import_holistic_issues` defaults missing `review_scope.full_sweep_included` to `None` (holistic.py L62-68)
**CONFIRMED.** At `holistic.py:62-66`:
```python
review_scope = issues_data.get("review_scope", {})
if not isinstance(review_scope, dict):
    review_scope = {}
review_scope.setdefault("full_sweep_included", None)
scope_full_sweep = review_scope.get("full_sweep_included")
```
When `full_sweep_included` is absent or non-boolean, `scope_full_sweep` becomes `None`.

### 2. `detect_review_coverage` treats anything except explicit `False` as full-sweep eligible (review_coverage.py L170-171, L65)
**CONFIRMED.** At `review_coverage.py:170-171`:
```python
full_sweep_included = holistic_cache.get("full_sweep_included")
if full_sweep_included is not False:
```
`None is not False` evaluates to `True`, so missing/unset `full_sweep_included` is treated as a full sweep. When `holistic_fresh=True` is subsequently set, `_check_file_review_status` at line 65 returns `None` for unreviewed files — suppressing their detection.

### 3. `update_holistic_review_cache` records metadata even with `issue_count=0` and conditional `file_count_at_review` (holistic_cache.py L86-98)
**CONFIRMED.** The function creates `holistic_entry` with `issue_count: len(valid)` (can be 0) and `file_count_at_review: resolved_total_files` (can fall back to 0 via `_resolve_total_files`). Crucially, `full_sweep_included` is only stored if it's an explicit boolean (line 97-98: `if isinstance(full_sweep_included, bool)`). When it's `None`, it's omitted from the cache entry, causing the `holistic_cache.get("full_sweep_included")` in `detect_review_coverage` to return `None`.

### 4. `resolve_holistic_coverage_issues` auto-resolves open holistic markers with `scan_verified=False` (holistic_cache.py L124-133)
**CONFIRMED.** The function converts any open `subjective_review` issue with `::holistic_unreviewed` or `::holistic_stale` in its ID to `auto_resolved` status with `scan_verified: False`.

### 5. Strict scoring does not treat `auto_resolved` as failing (core.py L191-194)
**CONFIRMED.** `FAILURE_STATUSES_BY_MODE` at `core.py:191-194`:
- lenient: `{"open"}`
- strict: `{"open", "wontfix"}`
- verified_strict: `{"open", "wontfix", "fixed", "false_positive"}`

`auto_resolved` is absent from all sets, so auto-resolved issues never count as failures.

## Chain Summary

1. Empty holistic import → `full_sweep_included` defaults to `None`
2. `update_holistic_review_cache` omits `None` (only stores booleans) → cache has no `full_sweep_included` key
3. `resolve_holistic_coverage_issues` converts open holistic markers to `auto_resolved`
4. On next scan, `detect_review_coverage` reads `holistic_cache.get("full_sweep_included")` → `None` → `None is not False` → treats as full sweep → `holistic_fresh=True` → suppresses regeneration of unreviewed-file issues
5. `auto_resolved` not in `FAILURE_STATUSES_BY_MODE` → score improves without real review evidence

## Duplicate Check

- **S118** (@kmccleary3301): Identifies `do_import_run` omitting `review_scope` entirely, leading to the same `None`-as-full-sweep downstream effect. Different entry path (replay vs. normal import), but same root `is not False` pattern exploited. Partial overlap.
- **S088** (@juzigu40-ui, same author): Covers scan_path auto-resolution laundering into `scan_verified`. Different mechanism (scope-based vs. holistic sweep logic).
- **S152** (@mpoffizial): Covers `auto_resolve_disappeared()` status laundering. Different auto-resolve trigger.

S154 adds novel analysis of the tri-state `full_sweep_included` logic and the `update_holistic_review_cache` caching behavior that S118 does not cover.

## Assessment

The core observation is valid: the `is not False` tri-state check on `full_sweep_included` creates a path where an empty holistic import (zero issues, no explicit scope) can suppress coverage debt and improve scores without review evidence.

Caveats:
1. **Requires specific conditions**: An empty holistic import must occur without explicit `review_scope.full_sweep_included = false`. Normal well-formed imports include this field.
2. **Partial overlap with S118**: Both submissions exploit the same downstream `None is not False` behavior, though through different entry paths.
3. **The repro claim (28.0 → 40.0)** is plausible given the chain but cannot be independently verified without replicating the exact state setup.
4. **Intentional design trade-off**: The tri-state logic (`True`/`False`/`None`) may be deliberate to handle legacy states where `full_sweep_included` was not yet tracked.
