# Bounty Verification: S129 @yv-was-taken — Silent Suppression Loss on Out-of-Scope Auto-Resolution

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4005041585
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `_mark_auto_resolved()` unconditionally clears suppression fields
**CONFIRMED.** At `desloppify/engine/_state/merge_issues.py:49-56`, `_mark_auto_resolved()` sets `suppressed=False`, `suppressed_at=None`, `suppression_pattern=None` unconditionally.

### 2. Called for both genuinely disappeared AND out-of-scope issues
**CONFIRMED.** The out-of-scope path at `merge_issues.py:107-115` calls `_mark_auto_resolved()` with a scope note, and the disappeared-issue path at `merge_issues.py:123-132` calls it with a different note. Same function, both paths.

### 3. Suppression is "permanently destroyed" — user must re-suppress
**NOT CONFIRMED.** This is the critical claim, and it is wrong. Suppression in this codebase is **derived state**, not standalone user data. Every call to `upsert_issues()` recomputes suppression from the current ignore patterns:

- `merge_issues.py:164`: `matched_ignore = matched_ignore_pattern(issue_id, issue["file"], ignore)`
- If matched → `merge_issues.py:190-193`: sets `suppressed=True`, `suppressed_at=now`, `suppression_pattern=matched_ignore`, then `continue` (skipping reopen)
- If not matched → `merge_issues.py:195-197`: sets `suppressed=False` regardless

When the issue comes back into scope on a wider scan, `upsert_issues()` re-checks ignore patterns and re-suppresses if the pattern still exists in config. The user never sees the issue as open+unsuppressed.

### 4. Impact: "frustrating cycle where users must re-suppress the same issues"
**NOT CONFIRMED.** Suppression is set via `add_ignore()` in `filtering.py:135`, which adds the pattern to `state["config"]["ignore"]`. This config persists across scans. `upsert_issues()` receives the ignore list and re-applies suppression automatically. Users never need to re-suppress.

## Duplicate Check

No prior submission covers `_mark_auto_resolved()` suppression clearing.

## Code Trace

1. `_mark_auto_resolved()` at `merge_issues.py:49-56` — clears suppression (confirmed)
2. Out-of-scope caller at `merge_issues.py:107-115` — calls it for scope-filtered issues (confirmed)
3. `upsert_issues()` at `merge_issues.py:164,190-197` — **always overwrites** suppression from ignore patterns, making the clearing in step 1 irrelevant
4. `add_ignore()` at `filtering.py:135` — adds pattern to persistent config, ensuring it survives across scans
5. Suppression is ONLY set in two places: `filtering.py:126` and `merge_issues.py:170,192` — both derive from ignore patterns, never from independent user state

## Verdict

The submission correctly identifies that `_mark_auto_resolved()` clears suppression fields unnecessarily for out-of-scope issues. However, the claimed impact — permanent data loss requiring manual re-suppression — does not occur. Suppression is derived state recomputed from ignore patterns on every scan cycle. The clearing is cosmetically unnecessary (and could be cleaned up) but is functionally harmless.

**Final verdict: NO**
