# Bounty Verification: S123 @leanderriefel — Split-brain plan persistence

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4004451912
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `plan` CLI includes `--state` argument
**CONFIRMED.** `parser_groups_plan_impl.py:361` adds `--state` argument to the plan parser.

### 2. Runtime carries resolved state path
**CONFIRMED.** `runtime.py:24-37` defines `CommandRuntime` with `state_path: Path | None`, and `command_runtime()` resolves it from args.

### 3. Plan persistence supports both global and state-derived paths
**CONFIRMED.** `persistence.py:24` defines `PLAN_FILE = STATE_DIR / "plan.json"` as global default. `persistence.py:27` accepts optional `path` parameter. `persistence.py:103-105` provides `plan_path_for_state()` helper.

### 4. Some handlers correctly scope plan to state
**CONFIRMED.** `override_handlers.py:233-235` and `302-304` use `_plan_file_for_state(state_file)` to derive the plan path from the state path before calling `load_plan(plan_file)`.

### 5. Many handlers bypass state scope and use global `load_plan()`
**PARTIALLY CONFIRMED.**
- `cmd.py:88` — `plan = load_plan()` — **CONFIRMED**, no path argument
- `reorder_handlers.py:49` — `plan = load_plan()` — **CONFIRMED**, no path argument
- `queue_render.py:179` — `plan = load_plan()` — **CONFIRMED**, no path argument
- `commit_log_handlers.py:119` — **INACCURATE**: line 119 is `state = state_mod.load_state()`, not `load_plan()`. The actual global `load_plan()` call is at line 193 in `cmd_commit_log_dispatch()`.
- `commit_log_handlers.py:171` — **INACCURATE**: line 171 is `state = state_mod.load_state()`, not `load_plan()`. Same pattern (global default without state scoping) but different function.

3 of 5 specific line citations are accurate for `load_plan()`. The other 2 cite `load_state()` calls, which exhibit the same scoping gap but for a different function than claimed.

## Duplicate Check
- S195 (@AlexChen31337) covers related ground: `STATE_DIR`/`PLAN_FILE` constants baked in at import time breaking `RuntimeContext.project_root`. Related root cause but different angle — S195 is about module-level constants vs runtime override, S123 is about handler-level inconsistency in using the `--state` argument. Distinct enough to not be a duplicate.
- No other submissions found covering this exact handler-level plan scoping inconsistency.

## Assessment
The core observation is valid: there is a genuine inconsistency where some plan handlers respect `--state` scoping and others silently fall back to the global `PLAN_FILE`. This creates a contract violation where the CLI promises state-scoped behavior but only delivers it for some subcommands.

However, caveats apply:
1. **Citation inaccuracies**: 2 of 5 line references (commit_log_handlers.py:119,171) point to `load_state()` calls, not `load_plan()` as claimed.
2. **Uncommon workflow**: `--state` with a non-default path is not the typical usage pattern. Most users use the default state file, making this a latent bug.
3. **No evidence of user breakage**: The submission describes theoretical "queue/cluster/commit tracking drift" but provides no evidence this has occurred in practice.
4. **Moderate blast radius**: Only affects multi-state workflows, which appear to be an advanced/uncommon feature.
