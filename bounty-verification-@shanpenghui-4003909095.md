# Bounty Verification: S119 @shanpenghui

## Submission

Duplicate action-priority tables with contradictory ordering.

## Evidence

At commit `6eb2065`:

1. **`desloppify/engine/_work_queue/helpers.py:15`**
   ```python
   ACTION_TYPE_PRIORITY = {"auto_fix": 0, "refactor": 1, "manual_fix": 2, "reorganize": 3}
   ```
   Used by `ranking.py:209` to sort clusters in `_natural_sort_key`.

2. **`desloppify/base/registry.py:455`**
   ```python
   _ACTION_PRIORITY = {"auto_fix": 0, "reorganize": 1, "refactor": 2, "manual_fix": 3}
   ```
   Used by `dimension_action_type()` at line 470 to pick the best action label for a dimension.

`refactor` and `reorganize` are swapped between the two tables. `manual_fix` also differs (2 vs 3).

## Verdict

**YES** — Both claims confirmed. Two independent priority tables cover the same four action types with contradictory orderings. No single source of truth exists.

## Fix

- Renamed `_ACTION_PRIORITY` in `base/registry.py` to `ACTION_TYPE_PRIORITY` (public).
- Removed the duplicate definition from `helpers.py`; it now imports `ACTION_TYPE_PRIORITY` from `base.registry`.
- The registry ordering (`reorganize=1, refactor=2`) is canonical since `base/registry.py` is the authoritative source for detector metadata.

## Scores

| Criterion | Score |
|-----------|-------|
| Signal | 4/10 |
| Originality | 4/10 |
| Core Impact | 1/10 |
| Overall | 3/10 |
