# Bounty Verification: @leanderriefel — Split-Brain Plan Persistence

**Scoreboard ID:** S329
**Comment ID:** 4004451912
**Verdict:** YES (VERIFIED+FIXED)
**Date:** 2026-03-07

---

## Claim

**Raw:** Many plan subcommand handlers call bare `load_plan()` ignoring the `--state`-derived plan path, while only `skip`, `unskip`, and `reopen` correctly call `_plan_file_for_state()`. This creates split-brain plan persistence: with a non-default `--state` path, skip/unskip/reopen correctly modify the co-located `plan.json` while all other handlers silently read/write the default global `plan.json`.

**Distilled:** Plan handlers have split-brain plan persistence — skip/unskip/reopen scope to `--state` path but all other handlers always use the global default `plan.json`.

**Restated:** 19 plan subcommand call sites used bare `load_plan()` (resolving to `PLAN_FILE`, the global default), while `cmd_plan_skip`, `cmd_plan_unskip`, and `cmd_plan_reopen` correctly derived the plan path via `plan_path_for_state(runtime.state_path)`. When a user passed `--state` pointing to a non-default directory, the three correct handlers loaded/saved to the co-located `plan.json` while the remaining 19 handlers silently operated on the default `.desloppify/plan.json`.

---

## Code Verification

### persistence.py

```python
# persistence.py:24 — hardcoded default
PLAN_FILE = STATE_DIR / "plan.json"

# persistence.py:27-29 — no-arg form uses PLAN_FILE
def load_plan(path: Path | None = None) -> PlanModel:
    plan_path = path or PLAN_FILE

# persistence.py:103-105 — correct path derivation
def plan_path_for_state(state_path: Path) -> Path:
    return state_path.parent / "plan.json"
```

### Handlers at submission time (bare `load_plan()` — WRONG)

| File | Handler | Fix Status |
|------|---------|------------|
| `override_handlers.py` | `cmd_plan_describe` | Fixed PR #406 |
| `override_handlers.py` | `cmd_plan_note` | Fixed PR #406 |
| `reorder_handlers.py` | `cmd_plan_reorder` | Fixed PR #406 |
| `queue_render.py` | `cmd_plan_queue` | Fixed PR #406 |
| `commit_log_handlers.py` | `cmd_commit_log_dispatch` | Fixed PR #406 |
| `cmd.py` | `_cmd_plan_show` | Fixed PR #406 |
| `cmd.py` | `_cmd_plan_reset` | Fixed PR #406 |
| `cluster_handlers.py` | 9 handlers | Fixed PR #406 |
| `override_handlers.py` | `cmd_plan_resolve` (2 paths) | Fixed PR #407 |
| `override_handlers.py` | `cmd_plan_focus` | Fixed PR #407 |
| `override_handlers.py` | `cmd_plan_scan_gate` | Fixed PR #407 |
| `move_handlers.py` | `cmd_plan_move` | Fixed PR #407 |
| `triage/reflect.py` | `cmd_stage_reflect` | Fixed PR #407 |
| `triage/organize.py` | `cmd_stage_organize` | Fixed PR #407 |
| `triage/stage_persistence.py` | `record_triage_stage` | Fixed PR #407 |

### Handlers at submission time (correct `_plan_file_for_state()`)

```python
# cmd_plan_skip — override_handlers.py
state_file = runtime.state_path
plan_file = _plan_file_for_state(state_file)
plan = load_plan(plan_file)

# cmd_plan_unskip — override_handlers.py
state_file = runtime.state_path
plan_file = _plan_file_for_state(state_file)
plan = load_plan(plan_file)

# cmd_plan_reopen — override_handlers.py
plan_file = _plan_file_for_state(state_file)
plan = load_plan(plan_file)
```

### Current code (post-fix, verified)

All handlers now follow the correct pattern:
```python
plan_file = plan_path_for_state(runtime.state_path) if runtime.state_path else None
plan = load_plan(plan_file)
```

Confirmed in: `reorder_handlers.py:50-51`, `queue_render.py:179-180`, `commit_log_handlers.py:197-198`, `cmd.py:104-105`, `cmd.py:169`, `override_handlers.py:126`, `override_handlers.py:153`.

---

## Impact

**Trigger condition:** Only affects users with non-default `--state` paths. Default usage (`.desloppify/state.json`) was unaffected because `plan_path_for_state()` resolves to the same `.desloppify/plan.json` as `PLAN_FILE`.

**Failure scenario:**
1. `desloppify plan skip <id> --state /project-B/state.json` → correctly marks skip in `/project-B/plan.json`
2. `desloppify plan queue --state /project-B/state.json` → silently loads default `plan.json`, shows stale data
3. `desloppify plan describe <id> "..." --state /project-B/state.json` → writes description to default `plan.json`

Silent data routing to wrong plan file, no error, no warning.

---

## Verdict: YES (VERIFIED+FIXED)

Claim confirmed. The split-brain was real and systematic at time of submission. Fix complete in PR #406 and PR #407. No code changes needed in this verification PR — the fix is already in `main`.

| Dimension | Score |
|-----------|-------|
| Signal (significance) | 5/10 |
| Originality | 5/10 |
| Core Impact | 5/10 |
| Overall | 5/10 |
