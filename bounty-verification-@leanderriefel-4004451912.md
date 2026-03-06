# Bounty Verification: @leanderriefel — Plan State-Path Inconsistency

**Verdict: YES**
**Comment ID:** 4004451912
**Date:** 2026-03-06

---

## Submission Summary

The submission claims that many `plan` subcommand handlers call bare `load_plan()` without
respecting the state-derived plan path, while a subset of handlers in `override_handlers.py`
(skip, unskip, reopen) correctly derive the plan path from the state file location via
`_plan_file_for_state()`.

---

## Verification

### Claim 1: Bare `load_plan()` calls in plan handlers

**Status: CONFIRMED**

The following handlers all call `load_plan()` without a path argument, unconditionally loading
from the default `PLAN_FILE` (`.desloppify/plan.json`):

| File | Handler | Line |
|---|---|---|
| `override_handlers.py` | `cmd_plan_describe` | 125 |
| `override_handlers.py` | `cmd_plan_note` | 150 |
| `override_handlers.py` | `cmd_plan_focus` | 744 |
| `override_handlers.py` | `cmd_plan_scan_gate` | 782 |
| `override_handlers.py` | `cmd_plan_resolve` (synthetic block) | 511, 693, 702 |
| `reorder_handlers.py` | `cmd_plan_reorder` | 49 |
| `commit_log_handlers.py` | `cmd_commit_log_dispatch` | 193 |
| `queue_render.py` | `cmd_plan_queue` | 179 |
| `cmd.py` | `_cmd_plan_show` | 102 |
| `cmd.py` | `_cmd_plan_reset` | 165 |
| `cluster_handlers.py` | `_cmd_cluster_create` | 94 |
| `cluster_handlers.py` | `_cmd_cluster_add` | 117 |
| `cluster_handlers.py` | `_cmd_cluster_remove` | 169 |
| `cluster_handlers.py` | `_cmd_cluster_delete` | 197 |
| `cluster_handlers.py` | `_cmd_cluster_reorder` | 363 |
| `cluster_handlers.py` | `_cmd_cluster_show` | 401 |
| `cluster_handlers.py` | `_cmd_cluster_list` | 494 |
| `cluster_handlers.py` | `_cmd_cluster_update` | 532 |
| `cluster_handlers.py` | `_cmd_cluster_merge` | 565 |

### Claim 2: Only skip/unskip/reopen use `_plan_file_for_state()`

**Status: CONFIRMED**

In `override_handlers.py`:
- `cmd_plan_skip` (lines 241–243): `state_file = runtime.state_path; plan_file = _plan_file_for_state(state_file); plan = load_plan(plan_file)`
- `cmd_plan_unskip` (lines 310–312): same pattern
- `cmd_plan_reopen` (lines 354–355): same pattern

These three are the only handlers that correctly thread the state path through to plan loading.

### Claim 3: Standard workflows are not affected

**Status: CONFIRMED**

`persistence.py:103–105`:
```python
def plan_path_for_state(state_path: Path) -> Path:
    """Derive plan.json path from a state file path."""
    return state_path.parent / "plan.json"
```

`PLAN_FILE = STATE_DIR / "plan.json"` where `STATE_DIR = .desloppify/`.

When `--state` is omitted (default), `state_path(args)` returns `None`, and
`command_runtime` sets `state_path=None`. Both `load_plan(None)` and
`load_plan(plan_path_for_state(default_state))` resolve to the same path.

The divergence is only observable when `--state` points to a non-default directory,
e.g. `--state /project/.desloppify/state-python.json`. In that scenario, skip/unskip/reopen
correctly target `.desloppify/plan.json` (co-located with state-python.json's parent), while
all other handlers incorrectly target the default `.desloppify/plan.json`.

In practice this matters for users leveraging per-language state files (`--lang python` etc.
if state is in a different directory). Within the default workflow, all handlers behave
consistently.

---

## Significance

**~5/10.** The inconsistency is real and systematic — 19 call sites wrong vs. 3 correct.
However, the practical blast radius is limited: the standard single-project workflow is
unaffected. Users who pass `--state` to a non-default path would experience silent plan
mismatches where skip/unskip writes to the correct plan but reorder/cluster/queue reads
from the wrong one. The pattern is architecturally wrong and will silently corrupt plan
state in affected configurations.

---

## Fix

The fix threads `plan_file` (derived from `runtime.state_path` or `state_path(args)`) into
all handlers that previously used bare `load_plan()`. Both `load_plan` and `save_plan` calls
are updated. Handlers that already call `command_runtime(args)` use `runtime.state_path`;
handlers that don't derive the path directly from `state_path(args)`.

No behavioural change for the default `--state` path: `plan_path_for_state(None)` is never
called; `load_plan(None)` continues to use `PLAN_FILE` as before.
