# Bounty Verification: S088 @juzigu40-ui — scan_path Auto-Resolution Score Inflation

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4002181008
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. Out-of-scope issues force-marked `auto_resolved` (merge_issues.py L104-L116)
**CONFIRMED.** `auto_resolve_disappeared()` at lines 104-116 checks if an issue's file is outside the current `scan_path` prefix. If so, it calls `_mark_auto_resolved()` with note "Out of current scan scope" and increments `resolved_out_of_scope`. The docstring explicitly states: "Out-of-scope issues are auto-resolved (not skipped) so they stop polluting queue counts."

### 2. `scan_verified: True` attestation written (merge_issues.py L49-L63)
**CONFIRMED.** `_mark_auto_resolved()` sets `resolution_attestation` with `"kind": "scan_verified"` and `"scan_verified": True`. This attestation is identical for both genuinely-disappeared issues and merely out-of-scope issues — no distinction in the attestation itself.

### 3. `auto_resolved` excluded from all failure modes (core.py L191-L195)
**CONFIRMED.** `FAILURE_STATUSES_BY_MODE` defines:
- `lenient`: `{"open"}`
- `strict`: `{"open", "wontfix"}`
- `verified_strict`: `{"open", "wontfix", "fixed", "false_positive"}`

None include `auto_resolved`, so auto-resolved issues (including out-of-scope ones) never count as failures in any scoring mode.

### 4. Score recomputation is path-scoped (state_integration.py L285-L298)
**CONFIRMED.** `recompute_stats()` calls `path_scoped_issues(state["issues"], scan_path)` to filter issues before computing stats and health scores. Issues outside the current scan_path are excluded from scoring entirely.

### 5. Queue defaults to `state["scan_path"]` (core.py L160-L163, ranking.py L136)
**CONFIRMED.** `_resolve_inputs()` defaults `scan_path` to `state.get("scan_path")`. `build_issue_items()` in ranking.py uses `path_scoped_issues(state.get("issues", {}), scan_path)` to scope the work queue.

### 6. Summary shows `auto_resolved` but not `resolved_out_of_scope` (summary.py L87-L93, merge.py L227)
**CONFIRMED.** `show_diff_summary()` displays `diff["auto_resolved"]` as the resolved count. `resolved_out_of_scope` is tracked in the diff dict (via `_build_merge_diff`) but never displayed to the user in the summary output. The word "resolved_out_of_scope" does not appear anywhere in `summary.py`.

## Duplicate Check
- **S129** (@yv-was-taken, 13:24 UTC): Focuses on suppression state loss during auto-resolution — a more specific sub-bug within the same mechanism.
- **S152** (@mpoffizial, 13:57 UTC): Focuses on wontfix/false_positive status laundering via auto-resolve — overlapping concern but narrower scope.
- **S250** (@Tib-Gridello, March 6th): Covers path-scoped scoring with potential inflation — overlapping but different angle (potentials vs issues).
- **S088 has priority** as the earliest submission (04:52 UTC March 5th) and the broadest framing.

## Assessment
The submission accurately identifies and traces through the full chain: narrowed scan_path → out-of-scope auto-resolution → scan_verified attestation → exclusion from failure sets → inflated scores → hidden from summary. All 7 code references are correct at snapshot.

However, caveats apply:
1. **Intentional design.** The docstring on `auto_resolve_disappeared` explicitly documents this as a design choice: "Re-scanning with a wider scan_path will reopen them via upsert." The reopening mechanism in `upsert_issues()` is confirmed functional.
2. **Note field distinguishes scope.** The `note` field reads "Out of current scan scope (scan_path: ...)" — distinguishing it from genuinely resolved issues at the data level, even if the UI doesn't surface this.
3. **Not exploitable without user action.** The user must actively narrow their scan path; this isn't a silent or automatic degradation.
4. **"Core integrity flaw" overstates severity.** This is a design trade-off with known recovery path, not a fundamental integrity violation. The system is internally consistent — it just doesn't guard against intentional scope narrowing.

The misleading `scan_verified: True` attestation on out-of-scope issues and the lack of user-visible distinction in the summary are the strongest concrete issues.
