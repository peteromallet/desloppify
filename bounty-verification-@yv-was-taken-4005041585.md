# Bounty Verification: yv-was-taken — comment 4005041585

**Submitter:** @yv-was-taken
**Comment ID:** 4005041585
**Verdict:** YES WITH CAVEATS
**Scores:** Sig 5 / Orig 5 / Core 1 / Overall 3
**Date:** 2026-03-06

---

## Problem Restatement (Independent)

The submission claims that `_mark_auto_resolved()` in `merge_issues.py` unconditionally clears suppression metadata for all issues it processes, including suppressed ones. The claimed mechanism: when a narrowed scan is run (`scan_path != "."`), issues outside the scan scope are auto-resolved via `_mark_auto_resolved()`, which wipes `suppressed`, `suppressed_at`, and `suppression_pattern`. The submission calls this "permanent suppression loss."

My independent code trace:

1. `auto_resolve_disappeared()` (`merge_issues.py:65`) iterates all existing issues.
2. Status guard (`lines 85-91`): skips issues already in current scan or with resolved/ignored statuses.
3. A suppressed issue with `status="open"` passes this guard — suppressed issues are NOT filtered out here.
4. Suspect detector guard (`lines 101-102`): skips import-only detectors like `"review"`. Suppressed issues from scan detectors pass through.
5. Out-of-scope check (`lines 104-116`): if `scan_path` is set and the issue file is outside scope, `_mark_auto_resolved()` is called directly with no suppression guard.
6. `_mark_auto_resolved()` (`lines 49-61`) unconditionally sets:
   ```python
   issue["suppressed"] = False
   issue["suppressed_at"] = None
   issue["suppression_pattern"] = None
   ```

**There is no `if previous.get("suppressed"): continue` guard anywhere in `auto_resolve_disappeared()`.**

The same applies to the normal-disappear path (`lines 122-131`) — a suppressed issue that is absent from the scan (e.g., its file was deleted) will also have suppression cleared by `_mark_auto_resolved()`.

---

## Claim Verification

### Claim 1: `_mark_auto_resolved()` clears suppression unconditionally — CONFIRMED

**Evidence:**

| File | Lines | Finding |
|------|-------|---------|
| `engine/_state/merge_issues.py` | 49–61 | `_mark_auto_resolved()` sets `suppressed=False`, `suppressed_at=None`, `suppression_pattern=None` with no conditions |
| `engine/_state/merge_issues.py` | 84–91 | Status guard: skips `issue_id in current_ids` or status not in `("open","wontfix","fixed","false_positive")`; suppressed=True issues with status="open" are NOT skipped |
| `engine/_state/merge_issues.py` | 101–102 | Suspect detector guard: only skips import-only detectors (e.g., `"review"`); scan-detector suppressed issues pass |
| `engine/_state/merge_issues.py` | 104–116 | Out-of-scope path: calls `_mark_auto_resolved()` directly with no suppression check |
| `engine/_state/merge_issues.py` | 118–133 | Normal-disappear path: calls `_mark_auto_resolved()` directly with no suppression check |

The flaw is confirmed: `auto_resolve_disappeared()` will call `_mark_auto_resolved()` on suppressed issues, clearing their suppression metadata.

---

### Claim 2: Suppression loss is permanent — OVERSTATED

**Evidence:**

On the next scan where the issue reappears within scope, `upsert_issues()` re-evaluates suppression:

```python
# merge_issues.py:160-162
matched_ignore = matched_ignore_pattern(issue_id, issue["file"], ignore)
```

If the ignore pattern still matches (`.sloppyignore` unchanged), suppression is re-applied at `lines 191-195`:
```python
if matched_ignore:
    previous["suppressed"] = True
    previous["suppressed_at"] = now
    previous["suppression_pattern"] = matched_ignore
    continue
```

So the suppression is recovered on the next in-scope scan. "Permanent" is inaccurate — it is temporary, scoped to the window between the narrow-path scan and the next broad scan.

**However**, the re-suppression path has its own problem: the `continue` at line 195 skips the reopening check at lines 201–223. After the re-suppression, the issue has:
- `status = "auto_resolved"` (from `_mark_auto_resolved()`)
- `suppressed = True` (re-applied by `upsert_issues()`)

This is an inconsistent state: the issue is effectively hidden (`match_issues()` filters `not issue.get("suppressed")`), but its `status` is `auto_resolved` rather than `open`. This was not identified by the submission.

---

## Timeline of States (Illustrative Scenario)

1. Issue present: `{status: "open", suppressed: True, suppression_pattern: "foo/*"}`
2. Narrow scan (issue out of scope): `_mark_auto_resolved()` called →
   `{status: "auto_resolved", suppressed: False, suppression_pattern: None}`
3. Next broad scan — issue reappears, pattern still in `.sloppyignore`:
   `upsert_issues()` → `{status: "auto_resolved", suppressed: True, suppression_pattern: "foo/*"}`
   *(inconsistent: status doesn't match suppressed state)*
4. If pattern later removed from `.sloppyignore` and issue reappears:
   `upsert_issues()` → `{status: "open"}` (correctly reopened via lines 201–223)

---

## Fix

**File:** `desloppify/engine/_state/merge_issues.py`

**Change:** Add a suppression guard in `auto_resolve_disappeared()` immediately after the suspect-detector check:

**Before (line 103 area):**
```python
        if previous.get("detector", "unknown") in suspect_detectors:
            continue

        if scan_path and scan_path != ".":
```

**After:**
```python
        if previous.get("detector", "unknown") in suspect_detectors:
            continue

        if previous.get("suppressed"):
            continue

        if scan_path and scan_path != ".":
```

**Rationale:** Suppressed issues were explicitly opted out of reporting by the user via ignore patterns. A scan should not be able to auto-resolve them — the ignore pattern, not the scan, is the authoritative source for suppression decisions. Skipping them here is consistent with how suspect detectors are handled.

---

## Files Examined

- `desloppify/engine/_state/merge_issues.py` — `_mark_auto_resolved()`, `auto_resolve_disappeared()`, `upsert_issues()`
- `desloppify/engine/_state/resolution.py` — `match_issues()` (confirms `not issue.get("suppressed")` filter), `resolve_issues()`
