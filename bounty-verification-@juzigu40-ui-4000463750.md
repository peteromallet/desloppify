# Bounty Verification: S003 @juzigu40-ui

**Issue:** https://github.com/peteromallet/desloppify/issues/204
**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4000463750
**Snapshot:** `6eb2065fd4b991b88988a0905f6da29ff4216bd8`

## Problem (in our own words)

The config migration path (`_migrate_from_state_files`) has a non-transactional design: when `config.json` doesn't exist, a read operation (`load_config`) triggers a destructive migration that strips config data from state files *before* ensuring the merged config is durably written to `config.json`. Additionally, glob-based file enumeration produces OS-dependent ordering, and scalar config values use first-writer-wins semantics, making the effective config non-deterministic across environments.

## Evidence

All four claims verified against snapshot `6eb2065`:

1. **Read path triggers migration** — `config.py:~L144`: `_load_config_payload` calls `_migrate_from_state_files(path)` when `config.json` doesn't exist. This couples a query operation with destructive side effects (CQS violation).

2. **Unstabilized source order + first-writer scalar precedence** — `config.py:~L396-401`: `state_dir.glob("state-*.json")` returns OS-dependent ordering. `config.py:~L322-336`: `_merge_config_value` sets scalars only when `key not in config` (first-writer-wins). With multiple state files containing different scalar values, the effective config depends on filesystem enumeration order.

3. **Source files rewritten before destination durability** — `config.py:~L357-381`: `_strip_config_from_state_file` is called inside `_migrate_single_state_file` (per-file), deleting `state["config"]` and rewriting the state file. `config.py:~L403-409`: `save_config` for the merged config is called *after* all state files have been stripped.

4. **Destination write failure is best-effort** — `config.py:~L403-409`: `save_config` is wrapped in try/except with `log_best_effort_failure`. If config.json write fails (permissions, full disk), the state files have already been stripped — config data is lost with no rollback.

## Fix

No fix included — this is a verification-only verdict.

## Verdict

| Question | Answer | Reasoning |
|----------|--------|-----------|
| **Is this poor engineering?** | YES | Non-transactional destructive migration on a read path violates CQS and risks silent data loss. |
| **Is this at least somewhat significant?** | YES | Config values (e.g. `target_strict_score`) feed scoring/queue decisions; silent convergence to defaults could alter runtime behavior. |

**Final verdict:** YES_WITH_CAVEATS

Caveats: This is a one-time migration path that only runs when `config.json` doesn't exist. The data-loss scenario requires a specific failure condition (config.json write failure after state files are stripped). Most users have 0-1 state files, limiting the non-deterministic ordering impact. The finding is technically sound but the practical risk window is narrow.

## Scores

| Criterion | Score |
|-----------|-------|
| Significance | 5/10 |
| Originality | 6/10 |
| Core Impact | 5/10 |
| Overall | 5/10 |

## Summary

S003 identifies a genuine non-transactional config migration with four verified claims: CQS-violating read-path side effects, non-deterministic glob ordering with first-writer-wins scalars, destructive source rewriting before destination persistence, and best-effort-only error handling. The finding is technically valid and well-documented with precise line references. Rated YES_WITH_CAVEATS due to the narrow practical risk window (one-time migration, requires write failure).

## Why Desloppify Missed This

- **What should catch:** A "transactional integrity" or "data migration safety" detector checking for destructive mutations before durable persistence.
- **Why not caught:** No detector specifically targets non-transactional migration patterns or CQS violations in config loading paths.
- **What could catch:** A detector that flags `del` / destructive writes followed by best-effort persistence in migration code paths.

## Previous Verdict Correction

The prior verdict (commit `71d2f95`) incorrectly marked S003 as "Duplicate of S313". S313 does not exist in the bounty submission data. This re-verification provides a proper assessment.
