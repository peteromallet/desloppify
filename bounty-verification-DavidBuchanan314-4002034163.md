# Bounty Verification: DavidBuchanan314 — S315

**Submitter:** @DavidBuchanan314
**Comment ID:** 4002034163
**Verdict:** YES WITH CAVEATS
**Scores:** Sig 4 / Orig 4 / Core 2 / Overall 3
**Date:** 2026-03-06

---

## Summary

The submission identifies a real issue: state and plan are written sequentially in `cmd_resolve`, with no transaction or rollback. A plan-save failure left the system in a desync state with no recovery path beyond a user warning. However, the submission overstates severity by calling this "corruption" (each individual write is atomic via temp+rename) and incorrectly characterizes the reconciliation behavior.

---

## Claim Verification

### Claim 1: State-then-plan sequential (non-atomic) writes — CONFIRMED

**Evidence:**
`desloppify/app/commands/resolve/cmd.py:180` — `save_state_or_exit(state, state_file)` runs before `_update_living_plan_after_resolve()` at line 182, which calls `save_plan()`.

The writes are sequential and non-transactional. A process killed between them leaves state updated (issues marked resolved/wontfix) while plan.json still lists those IDs in `queue_order`.

**Caveat:** "Corruption" is an overstatement. `safe_write_text` uses atomic temp+rename (`os.replace`), so neither file is ever in a partially-written state. The risk is a logical desync between the two files, not filesystem corruption.

---

### Claim 2: Plan-save failure is swallowed — CONFIRMED WITH CAVEAT

**Evidence:**
`save_plan()` in `desloppify/engine/_plan/persistence.py:96-100` raises `OSError` on write failure. The outer `except PLAN_LOAD_EXCEPTIONS` block in `_update_living_plan_after_resolve` (which includes `OSError`) catches this and prints a yellow warning to stderr, but previously took no recovery action.

The failure is caught (not "swallowed" silently) — but the response was insufficient: no retry, no reconciliation, no state rollback.

**Fix implemented:** The inner save is now wrapped in its own try/except. On failure, the code reloads the plan from disk, applies `reconcile_plan_after_scan(fresh_plan, state)` to supersede the now-resolved IDs, and retries `save_plan`. The warning is only shown if this recovery also fails.

---

### Claim 3: Reconciliation goes in the wrong direction / makes desync worse — INCORRECT

**Evidence:**
`desloppify/engine/_plan/reconcile.py:143` — `reconcile_plan_after_scan(plan, state)` iterates IDs referenced in the plan and calls `_is_issue_alive(state, fid)` for each. Issues not alive in state are moved to `plan["superseded"]` and removed from `queue_order`.

State is authoritative. Reconciliation goes **state → plan** (plan is corrected to match state). After a failed plan save during resolve:
- State has the resolved issues marked as `fixed`/`wontfix` (status ≠ `open`)
- `_is_issue_alive` returns `False` for them
- On the next `desloppify scan`, `reconcile_plan_after_scan` moves them to superseded

The desync **self-heals on the next scan** without any user intervention. The submission's characterization that reconciliation propagates incorrect state back or makes things worse is not supported by the code.

---

## Fix Details

**File:** `desloppify/app/commands/resolve/cmd.py`

**Changes:**
1. Added `reconcile_plan_after_scan` to the engine.plan imports
2. Added `state: dict` parameter to `_update_living_plan_after_resolve`
3. Wrapped `save_plan(plan)` in an inner try/except; on failure, reloads plan, reconciles against current state, retries save
4. Updated call site in `cmd_resolve` to pass `state=state`

**Rationale:** While the system would self-heal on the next scan, the immediate desync is user-visible (plan shows tasks that were already resolved). The emergency reconciliation closes this window when possible, without requiring a full scan.

---

## Files Examined

- `desloppify/app/commands/resolve/cmd.py` — state/plan write sequence, exception handling
- `desloppify/engine/_plan/persistence.py` — `save_plan` atomicity via `safe_write_text`
- `desloppify/engine/_state/persistence.py` — `save_state` atomicity via `safe_write_text`
- `desloppify/engine/_plan/reconcile.py` — `reconcile_plan_after_scan` direction confirmed state-authoritative
- `desloppify/app/commands/scan/plan_reconcile.py` — post-scan reconciliation flow
- `desloppify/app/commands/scan/workflow.py` — scan merge + reconcile call ordering
- `desloppify/base/discovery/file_paths.py` — `safe_write_text` uses `os.replace` for atomicity
- `desloppify/base/exception_sets.py` — `PLAN_LOAD_EXCEPTIONS` includes OSError
