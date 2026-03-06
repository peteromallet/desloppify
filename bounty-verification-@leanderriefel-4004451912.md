# Bounty Verification: leanderriefel — comment 4004451912

**Submitter:** @leanderriefel
**Comment ID:** 4004451912
**Verdict:** YES
**Scores:** Sig 5 / Orig 5 / Core 5 / Overall 5
**Date:** 2026-03-06

---

## Problem Restatement (Independent)

The submission claims a structural inconsistency in plan command handlers: some handlers (skip, unskip, reopen) correctly derive the plan file path from the runtime `state_path` via `_plan_file_for_state()`, while all other handlers call bare `load_plan()` — which always loads from the global `PLAN_FILE` constant regardless of any `--state` flag.

My independent code trace:

1. `persistence.py:24`: `PLAN_FILE = STATE_DIR / "plan.json"` — hardcoded default path.
2. `persistence.py:27-29`: `load_plan(path: Path | None = None)` — when called with no argument, uses `PLAN_FILE`.
3. `persistence.py:103-105`: `plan_path_for_state(state_path)` returns `state_path.parent / "plan.json"` — derives plan path co-located with a custom state file.
4. `override_handlers.py:72-75`: `_plan_file_for_state(state_file)` — helper that wraps `plan_path_for_state`, returns None for None input (which causes `load_plan()` to fall back to `PLAN_FILE`).
5. `runtime.py:24-37`: `command_runtime(args)` populates `state_path` from `state_path(args)`, which honours the `--state` CLI flag.

**Handlers that correctly propagate state_path → plan_file:**
- `cmd_plan_skip` (`override_handlers.py:241-243`): `state_file = runtime.state_path; plan_file = _plan_file_for_state(state_file); plan = load_plan(plan_file)`
- `cmd_plan_unskip` (`override_handlers.py:310-312`): same pattern
- `cmd_plan_reopen` (`override_handlers.py:354-355`): uses `state_path(args)` → `_plan_file_for_state()` → `load_plan(plan_file)`

**Handlers that do NOT (bare `load_plan()`):**
- `override_handlers.py:125` — `cmd_plan_describe`
- `override_handlers.py:150` — `cmd_plan_note`
- `reorder_handlers.py:49` — `cmd_plan_reorder`
- `queue_render.py:179` — `cmd_plan_queue`
- `commit_log_handlers.py:193` — `cmd_commit_log_dispatch`
- `cmd.py:102` — `_cmd_plan_show`
- `cmd.py:165` — `_cmd_plan_reset`
- `cluster_handlers.py:94,117,169,197,363,401,494,532,565` — 9 cluster handlers

---

## Claim Verification

### Claim 1: Many handlers call bare `load_plan()` — CONFIRMED

| File | Line | Handler | Issue |
|------|------|---------|-------|
| `override_handlers.py` | 125 | `cmd_plan_describe` | `plan = load_plan()` — no path |
| `override_handlers.py` | 150 | `cmd_plan_note` | `plan = load_plan()` — no path |
| `reorder_handlers.py` | 49 | `cmd_plan_reorder` | `plan = load_plan()` — no path |
| `queue_render.py` | 179 | `cmd_plan_queue` | `plan = load_plan()` — no path |
| `commit_log_handlers.py` | 193 | `cmd_commit_log_dispatch` | `plan = load_plan()` — no path |
| `cmd.py` | 102 | `_cmd_plan_show` | `plan = load_plan()` — no path |
| `cmd.py` | 165 | `_cmd_plan_reset` | `plan = load_plan()` — no path |
| `cluster_handlers.py` | 94,117,169,197 | create/add/remove/delete | `plan = load_plan()` — no path |
| `cluster_handlers.py` | 363,401,494,532,565 | reorder/show/list/update/merge | `plan = load_plan()` — no path |

### Claim 2: skip/unskip/reopen correctly use `_plan_file_for_state()` — CONFIRMED

```python
# cmd_plan_skip — override_handlers.py:241-243
state_file = runtime.state_path
plan_file = _plan_file_for_state(state_file)
plan = load_plan(plan_file)

# cmd_plan_unskip — override_handlers.py:310-312
state_file = runtime.state_path
plan_file = _plan_file_for_state(state_file)
plan = load_plan(plan_file)

# cmd_plan_reopen — override_handlers.py:354-355
plan_file = _plan_file_for_state(state_file)
plan = load_plan(plan_file)
```

Three handlers correctly derive plan path from runtime state. All others do not.

### Claim 3: Divergence only with non-default `--state` paths — CONFIRMED

When `--state` is the default (or omitted), `state_path(args)` returns the standard `.desloppify/state.json`, and `plan_path_for_state()` resolves to `.desloppify/plan.json` — same as `PLAN_FILE`. No divergence.

When `--state /some/other/dir/state.json` is passed, `plan_path_for_state()` returns `/some/other/dir/plan.json`. Skip/unskip/reopen correctly load that plan. All other handlers load the default `PLAN_FILE` instead — silently operating on the wrong file.

---

## Impact Assessment

**Scenario:** User has multiple isolated projects sharing one desloppify install, using `--state` to switch between them (or uses per-language state files).

1. User runs `desloppify plan skip <id>` → correctly marks skip in `/project-B/plan.json`
2. User runs `desloppify plan queue` → loads default `plan.json`, shows stale data
3. User runs `desloppify plan describe <id> "..."` → writes description to default `plan.json`, not `/project-B/plan.json`
4. Next `skip` sees the correctly updated plan; `describe` effects go to the wrong file

Silent data routing to the wrong plan file. No error, no warning.

---

## Fix

Thread `plan_file` (derived from `runtime.state_path` via `plan_path_for_state`) into all handlers that previously used bare `load_plan()`.

Pattern for handlers that already call `command_runtime(args)`:
```python
runtime = command_runtime(args)
state = runtime.state
plan_file = plan_path_for_state(runtime.state_path) if runtime.state_path else None
plan = load_plan(plan_file)
...
save_plan(plan, plan_file)
```

Pattern for handlers without state (cluster operations that don't need it):
```python
def _plan_file_from_args(args: argparse.Namespace) -> Path | None:
    sp = state_path(args)
    return plan_path_for_state(sp) if sp else None

plan_file = _plan_file_from_args(args)
plan = load_plan(plan_file)
...
save_plan(plan, plan_file)
```

**Files modified:** `override_handlers.py`, `reorder_handlers.py`, `commit_log_handlers.py`, `queue_render.py`, `cmd.py`, `cluster_handlers.py`

---

## Files Examined

- `desloppify/engine/_plan/persistence.py` — `load_plan()`, `plan_path_for_state()`, `PLAN_FILE`
- `desloppify/app/commands/helpers/runtime.py` — `CommandRuntime`, `command_runtime()`
- `desloppify/app/commands/plan/override_handlers.py` — skip/unskip/reopen (correct), describe/note (incorrect)
- `desloppify/app/commands/plan/reorder_handlers.py` — `cmd_plan_reorder` (incorrect)
- `desloppify/app/commands/plan/queue_render.py` — `cmd_plan_queue` (incorrect)
- `desloppify/app/commands/plan/commit_log_handlers.py` — `cmd_commit_log_dispatch` (incorrect)
- `desloppify/app/commands/plan/cmd.py` — `_cmd_plan_show`, `_cmd_plan_reset` (incorrect)
- `desloppify/app/commands/plan/cluster_handlers.py` — 9 handlers (all incorrect)
