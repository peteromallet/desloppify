# Bounty Verification: S006 @agustif

## Submission
Plan persistence uses a destructive read-path migration strategy that can erase user intent, instead of fail-safe schema handling.

## Evidence Trace (at commit 6eb2065)

### Claim 1: Newer-version plans warned but still mutated
**CONFIRMED.** `desloppify/engine/_plan/persistence.py:58-67` — when `version > PLAN_VERSION`, the code prints a warning to stderr but continues to call `ensure_plan_defaults(data)` which invokes `upgrade_plan_to_v7()`, mutating the plan in-place.

### Claim 2: `ensure_plan_defaults` always runs migration/coercion on read
**CONFIRMED.** `desloppify/engine/_plan/schema.py:198-204` — `ensure_plan_defaults()` calls `_upgrade_plan_to_v7(plan)` unconditionally. Every `load_plan()` call triggers the full migration pipeline.

### Claim 3: Migration coerces wrong shapes to empty containers
**CONFIRMED.** `desloppify/engine/_plan/schema_migrations.py:25-30` — `_ensure_container()` replaces any value not matching the expected type with a fresh empty container. Line 42's `ensure_container_types()` applies this to queue_order, deferred, skipped, overrides, clusters, superseded, promoted_ids, plan_start_scores, execution_log, and epic_triage_meta.

### Claim 4: Force-sets version to v7 even for newer input
**CONFIRMED.** `desloppify/engine/_plan/schema_migrations.py` end of `upgrade_plan_to_v7()`: `if plan.get("version") != V7_SCHEMA_VERSION: plan["version"] = V7_SCHEMA_VERSION`. A v8+ plan loaded by an older tool version would be silently downgraded to v7.

### Claim 5: Drops to fresh empty plan on invariant failure
**CONFIRMED.** `desloppify/engine/_plan/persistence.py:69-73` — if `validate_plan(data)` raises `ValueError`, returns `empty_plan()` with a warning.

### Claim 6: Normal flows then save that result
**PARTIALLY CONFIRMED.** `desloppify/app/commands/scan/preflight.py:47-50` — `save_plan(plan)` is called only in the `--force-rescan` code path, not on every load. However, other code paths (plan commands, triage) do load-then-save, so the concern is valid in aggregate, just overstated for the preflight example.

### Claim 7: Related pattern in state persistence
**CONFIRMED.** `desloppify/engine/_state/schema.py:379-431` (`ensure_state_defaults`) coerces wrong types to empty containers. `desloppify/engine/_state/persistence.py:128-138` falls back to `empty_state()` on normalization failure. Same warn-coerce-fallback pattern.

## Mitigating Factors
- Plans are regenerable via `desloppify scan` — data loss is recoverable
- Backups (`.json.bak`) are created before every save
- Warnings are printed to stderr on every fallback path
- This is a CLI tool, not a database — the tradeoff favoring availability over strict consistency is defensible
- Forward-compatibility (handling newer schema versions) is inherently difficult

## Verdict
The submission is factually accurate and identifies a real architectural pattern where read-time migration can silently lose data. The most concrete risk is the version downgrade path (v8+ to v7). However, the framing overstates severity — the tool has backup mechanisms, warnings, and plans are regenerable. This is a moderate design concern, not a critical reliability flaw.
