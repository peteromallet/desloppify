# Bounty Verification: S152 @mpoffizial

**Submission:** Status laundering via auto-resolve: `wontfix`/`false_positive` penalties permanently erased by code changes

## Problem (in our own words)

`auto_resolve_disappeared()` in `merge_issues.py` processes issues with status `open`, `wontfix`, `fixed`, or `false_positive` when they vanish from scan output. It converts them all to `auto_resolved` via `_mark_auto_resolved()`. However, `auto_resolved` is not present in any `FAILURE_STATUSES_BY_MODE` set in `core.py`. This means that issues which carried scoring penalties under `strict` mode (for `wontfix`) or `verified_strict` mode (for `wontfix`, `fixed`, `false_positive`) lose those penalties permanently once the underlying code changes enough that the detector no longer fires.

## Evidence

- `desloppify/engine/_state/merge_issues.py:85-89` (at commit `6eb2065`): `auto_resolve_disappeared()` processes issues with status in `("open", "wontfix", "fixed", "false_positive")`
- `desloppify/engine/_state/merge_issues.py:51` (at commit `6eb2065`): `_mark_auto_resolved()` sets `issue["status"] = "auto_resolved"`
- `desloppify/engine/_scoring/policy/core.py:191-195` (at commit `6eb2065`): `FAILURE_STATUSES_BY_MODE` does not include `auto_resolved` in any mode
- `desloppify/engine/_scoring/detection.py:99,166` (at commit `6eb2065`): Scoring loops skip issues whose status is not in `FAILURE_STATUSES_BY_MODE[mode]`

The chain is: mark issue `wontfix`/`false_positive` → code changes → issue disappears from scan → `auto_resolve_disappeared` sets status to `auto_resolved` → scoring no longer counts it as a failure → penalty erased.

## Fix

Either:
1. Add `auto_resolved` variants (e.g. `auto_resolved_from_wontfix`) to the appropriate failure sets
2. Skip auto-resolution for issues with penalty-carrying statuses (`wontfix`, `false_positive`)
3. Preserve the original status in a field that scoring checks

## Verdict

| Question | Answer | Reasoning |
|----------|--------|-----------|
| **Is this poor engineering?** | YES | The `verified_strict` mode exists specifically to penalize dismissed findings, but `auto_resolve_disappeared` silently erases those penalties |
| **Is this at least somewhat significant?** | YES | Undermines the integrity guarantee of strict scoring modes — users can game scores by making code changes after dismissing findings |

**Final verdict:** YES

## Scores

| Criterion | Score |
|-----------|-------|
| Significance | 7/10 |
| Originality | 5/10 |
| Core Impact | 7/10 |
| Overall | 6/10 |

## Summary

The submission correctly identifies that `auto_resolve_disappeared()` converts penalty-carrying statuses (`wontfix`, `fixed`, `false_positive`) to `auto_resolved`, which is absent from all `FAILURE_STATUSES_BY_MODE` sets. This permanently erases scoring penalties when the underlying code changes. The finding is technically accurate and represents a real gap in scoring integrity. Originality is moderate because related submissions (S033, S088, S127) cover adjacent auto-resolve and false_positive scoring issues.

## Why Desloppify Missed This

- **What should catch:** A cross-module invariant checker that validates all status transitions preserve scoring semantics
- **Why not caught:** Auto-resolve and scoring are in separate modules (`_state/merge_issues.py` vs `_scoring/policy/core.py`) with no shared contract enforcement
- **What could catch:** A detector that traces status transitions and validates they maintain scoring invariants across module boundaries
