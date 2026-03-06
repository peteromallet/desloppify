# Bounty Verification: @leanderriefel — Plan State-Path Inconsistency

**Verdict: YES (CONFIRMED)**
**Comment ID:** 4004451912
**Submission ID:** S329
**Date:** 2026-03-06

---

## Status

**VERIFIED + FIXED**

The core claim is confirmed by direct code inspection of all six referenced handler files.
The fix was implemented in commit `a24603f` (task #434), threading `plan_path_for_state(runtime.state_path)` through all affected handlers.

---

## Evidence

The submission claims that plan subcommand handlers call bare `load_plan()` without respecting
the `--state`-derived plan path, while skip/unskip/reopen in `override_handlers.py` do it correctly.

### Pre-fix bare `load_plan()` call sites confirmed:

| File | Handler | Notes |
|---|---|---|
| `override_handlers.py` | `cmd_plan_describe` | bare `load_plan()` |
| `override_handlers.py` | `cmd_plan_note` | bare `load_plan()` |
| `reorder_handlers.py` | `cmd_plan_reorder` | bare `load_plan()` |
| `commit_log_handlers.py` | `cmd_commit_log_dispatch` | bare `load_plan()` |
| `queue_render.py` | `cmd_plan_queue` | bare `load_plan()` |
| `cmd.py` | `_cmd_plan_show` | bare `load_plan()` |
| `cmd.py` | `_cmd_plan_reset` | bare `load_plan()` |
| `cluster_handlers.py` | `_cmd_cluster_create` | bare `load_plan()` |
| `cluster_handlers.py` | `_cmd_cluster_add` | bare `load_plan()` |
| `cluster_handlers.py` | `_cmd_cluster_remove` | bare `load_plan()` |
| `cluster_handlers.py` | `_cmd_cluster_delete` | bare `load_plan()` |
| `cluster_handlers.py` | `_cmd_cluster_reorder` | bare `load_plan()` |
| `cluster_handlers.py` | `_cmd_cluster_show` | bare `load_plan()` |
| `cluster_handlers.py` | `_cmd_cluster_list` | bare `load_plan()` |
| `cluster_handlers.py` | `_cmd_cluster_update` | bare `load_plan()` |
| `cluster_handlers.py` | `_cmd_cluster_merge` | bare `load_plan()` |

### Correctly-implemented handlers (as claimed):

- `cmd_plan_skip`: `state_file = runtime.state_path; plan_file = _plan_file_for_state(state_file); plan = load_plan(plan_file)`
- `cmd_plan_unskip`: same pattern
- `cmd_plan_reopen`: same pattern

### Root divergence mechanism:

When `--state` is omitted (default), both `load_plan(None)` and
`load_plan(plan_path_for_state(default_state))` resolve to the same `.desloppify/plan.json`.
When `--state /path/to/state-python.json` is passed, skip/unskip/reopen correctly target
`/path/to/plan.json` while all other handlers still target the default `.desloppify/plan.json`.

---

## Scores

| Dimension | Score (1–10) |
|---|---|
| **Accuracy** | 9 |
| **Significance** | 5 |
| **Originality** | 5 |
| **CoreImpact** | 5 |
| **Overall** | 5 |

**Accuracy 9/10:** File paths and handler names are correct. Minor deduction for line numbers being
slightly off in the original submission vs actual pre-fix positions. The asymmetry claim (19+ wrong
vs 3 correct) is accurate.

**Significance 5/10:** Real and systematic (16 affected handlers in commit a24603f, more in other
handlers). Limited blast radius — only triggered by non-default `--state` configurations.

**Originality 5/10:** Non-obvious finding requiring cross-file analysis of a subtle path-threading
inconsistency. Not derivable from earlier submissions.

**CoreImpact 5/10:** Does not affect the scoring engine directly, but corrupts plan state for users
with custom state paths (per-language scans, monorepo setups). No direct score-gaming vector.

**Overall 5/10:** Real, accurate, architectural bug with modest real-world impact.

---

## Enrichment Answers

**1. How accurate were the submitter's code references?**
Highly accurate. All referenced files exist, all referenced handler functions exist, and the
asymmetry between bare-load and path-threaded handlers is exactly as described. Minor imprecision
in specific line numbers (expected — lines shift between submission and verification). The core
technical claim is precise and verifiable.

**2. What is the real-world blast radius?**
Limited to users who invoke `desloppify plan <subcommand>` with a non-default `--state` flag
pointing to a different directory. In such cases, `plan skip` writes to the co-located plan.json
while `plan reorder`, `plan cluster add`, `plan queue`, etc. read/write the default plan.json.
This creates a silent divergence: the plan as seen by skip/unskip reflects the correct state,
while all other commands operate on a stale copy. Default single-project usage is unaffected.

**3. Is this an isolated bug or a systemic pattern?**
Systemic. The bug affects 16+ handlers across 6 files in commit a24603f alone, with additional
instances in focus/scan-gate/resolve/triage handlers. The root cause is that the helper function
`_plan_file_for_state()` was defined in `override_handlers.py` but never shared or applied
consistently. The three correct handlers (skip/unskip/reopen) were likely written by the same
author at the same time, while subsequent handlers were written without awareness of the pattern.

**4. How complex was the fix?**
Moderate. The mechanical fix is straightforward — replace `load_plan()` with
`load_plan(plan_path_for_state(runtime.state_path) if runtime.state_path else None)` at each
call site. But the scope is large (16 handlers in a24603f, additional handlers in other tasks),
and each fix also required threading `plan_file` into `save_plan()` calls and confirming
`None`-path fallback behavior. Test mocks required updating to supply `state_path=None`.

**5. Does this overlap with prior verified submissions?**
No meaningful overlap. The nearest related submission is S315 (@DavidBuchanan314 — cross-file
write consistency between state.json and plan.json), but S315 concerns atomic write ordering
across two files, not path-threading for non-default state locations. This submission identifies
a distinct bug class: intra-command path divergence where different handlers within a single
invocation context target different plan files.
