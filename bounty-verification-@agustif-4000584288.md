# Bounty Verification: agustif — S04

**Submitter:** @agustif
**Comment ID:** 4000584288
**Verdict:** YES WITH CAVEATS
**Scores:** Sig 5 / Orig 4 / Core 2 / Overall 3
**Date:** 2026-03-06

---

## Problem Restatement (Independent)

The submission claims that `load_plan()` uses a destructive read-path migration that can silently erase user intent when loading plans whose `version > PLAN_VERSION`.

The mechanism I found:

1. `persistence.py:59-65` — `load_plan()` checks `version > PLAN_VERSION` and prints a stderr warning, but continues processing.
2. `persistence.py:67` — `ensure_plan_defaults(data)` is called on the loaded plan dict.
3. `schema.py:198` — `ensure_plan_defaults()` always calls `upgrade_plan_to_v7(plan)`.
4. `schema_migrations.py:304-305` — `upgrade_plan_to_v7()` ends with:
   ```python
   if plan.get("version") != V7_SCHEMA_VERSION:
       plan["version"] = V7_SCHEMA_VERSION
       changed = True
   ```
   This runs **unconditionally** regardless of whether `original_version` was greater than or less than 7.
5. `persistence.py:80` — `save_plan()` also calls `ensure_plan_defaults(plan)` before writing, so any subsequent save of the loaded plan writes `version=7` to disk.

The result: a v8+ plan loaded and then saved by any command is permanently downgraded to v7 on disk.

---

## Claim Verification

### Claim 1: Destructive migration runs on version > PLAN_VERSION — CONFIRMED WITH CAVEAT

**Evidence:**
- `schema_migrations.py:304-305`: version is forced to `V7_SCHEMA_VERSION` unconditionally.
- `schema_migrations.py:270-278`: `needs_legacy_upgrade` is False for a v8+ plan with no legacy artifacts, so the data-migration functions (`migrate_deferred_to_skipped`, `migrate_epics_to_clusters`, etc.) do NOT run on v8+ plans.
- The version-reset at lines 304-305 is **outside** the `if needs_legacy_upgrade` block and always executes.

**Caveat:** "Silently" is not accurate. `persistence.py:60-65` does print:
```
Warning: Plan file version {version} is newer than supported ({PLAN_VERSION}). Some features may not work correctly.
```
The warning is inadequate (it doesn't mention the version downgrade on save) but it is not absent.

---

### Claim 2: User intent is erased — INCORRECT (overstated)

**Evidence:**
- `schema.py:195-197`: `ensure_plan_defaults()` uses `setdefault()` for all user-data fields. `queue_order`, `skipped`, `clusters`, `overrides`, `promoted_ids`, `execution_log`, etc. are NOT overwritten.
- `schema_migrations.py:228-234` (`_drop_legacy_plan_keys`): removes only a hardcoded set of legacy keys (`epics`, `epic_synthesis_meta`, `pending_plan_gate`, `uncommitted_findings`). None of these are user-authored data in the current schema.

The only forced mutation for a v8+ plan is `plan["version"] = 7`. User-authored plan content (queue ordering, skips, clusters, overrides) is preserved.

---

### Claim 3: The downgrade is permanent on save — CONFIRMED

**Evidence:**
- `persistence.py:80`: `save_plan()` calls `ensure_plan_defaults(plan)` before writing.
- `ensure_plan_defaults()` → `upgrade_plan_to_v7()` → version forced to 7.
- The on-disk plan is permanently written as version 7 after any command that saves the plan.

`load_plan()` itself does NOT auto-save, so the file is not immediately modified on read. But any command that mutates the plan (done, skip, focus, cluster operations, etc.) will write the downgraded version.

---

## Line Number Accuracy

The submission's line number references were not independently verifiable (the scoreboard notes "all line numbers wrong"). My independent verification uses:

| File | Line(s) | Finding |
|------|---------|---------|
| `engine/_plan/persistence.py` | 59-65 | version > PLAN_VERSION warning |
| `engine/_plan/persistence.py` | 67 | `ensure_plan_defaults(data)` called on load |
| `engine/_plan/persistence.py` | 80 | `ensure_plan_defaults(plan)` called on save |
| `engine/_plan/schema.py` | 190-198 | `ensure_plan_defaults()` calls `upgrade_plan_to_v7()` |
| `engine/_plan/schema_migrations.py` | 248-307 | `upgrade_plan_to_v7()` full function |
| `engine/_plan/schema_migrations.py` | 270-278 | `needs_legacy_upgrade` gate (version check) |
| `engine/_plan/schema_migrations.py` | 304-305 | Unconditional version force to 7 |

---

## Fix

**File:** `desloppify/engine/_plan/schema_migrations.py`

**Change:** At the end of `upgrade_plan_to_v7()`, the unconditional version reset is guarded to only apply when the original version was below `V7_SCHEMA_VERSION`:

**Before:**
```python
if plan.get("version") != V7_SCHEMA_VERSION:
    plan["version"] = V7_SCHEMA_VERSION
    changed = True
```

**After:**
```python
if original_version < V7_SCHEMA_VERSION:
    plan["version"] = V7_SCHEMA_VERSION
    changed = True
```

This preserves:
- v1–v6 plans: still upgraded to v7 (existing behavior)
- v7 plans: no change
- v8+ plans: version field is no longer forced down to 7

The warn-on-load in `persistence.py:60-65` is preserved. Plans with version > PLAN_VERSION still trigger the stderr warning — now without the destructive downgrade side effect.

---

## Files Examined

- `desloppify/engine/_plan/persistence.py` — `load_plan()`, `save_plan()`, version > PLAN_VERSION handling
- `desloppify/engine/_plan/schema.py` — `ensure_plan_defaults()`, `PLAN_VERSION = 7`
- `desloppify/engine/_plan/schema_migrations.py` — `upgrade_plan_to_v7()`, unconditional version reset
- `desloppify/engine/_state/schema.py` — reference only (state CURRENT_VERSION = 1, same pattern exists but separate)
- `desloppify/engine/_state/persistence.py` — reference only (analogous warning + load path)
- `desloppify/app/commands/scan/preflight.py` — reference only (uses `load_plan()` / `save_plan()`, would trigger the version downgrade)
