# Bounty Verification: S033 @xliry — false_positive Score Inflation Path

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4001601145
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. No validation when marking findings as false_positive
**CONFIRMED.** `resolve_issues()` (`desloppify/engine/_state/resolution.py:99-105`) accepts any status including `false_positive` for any matched issue. There is no check that the detector output actually changed or that the finding is genuinely a false positive. The attestation field is free-text with no enforcement.

### 2. false_positive findings never reopen on rescan
**CONFIRMED.** `upsert_issues()` (`desloppify/engine/_state/merge_issues.py:201`) only reopens issues with status `"fixed"` or `"auto_resolved"`:
```python
if previous["status"] in ("fixed", "auto_resolved"):
```
When a detector re-detects the same issue, a `false_positive` finding has its metadata updated (last_seen, tier, confidence, summary, detail at lines 179-185) but its status is preserved. The detector signals "this issue exists" but the system ignores it.

### 3. false_positive excluded from strict scoring
**CONFIRMED.** `FAILURE_STATUSES_BY_MODE` (`desloppify/engine/_scoring/policy/core.py:191-195`):
```python
"lenient": frozenset({"open"}),
"strict": frozenset({"open", "wontfix"}),
"verified_strict": frozenset({"open", "wontfix", "fixed", "false_positive"}),
```
`false_positive` is excluded from `strict` mode. The target system uses `target_strict_score` (`score_update.py:62`, `next/cmd.py:213`) and the `next` command uses `strict_score` for queue prioritization (`next/cmd.py:156, 298`).

### 4. verified_strict is display-only
**CONFIRMED.** `verified_strict_score` is computed and stored in state, appears in scan artifacts, status output, and agent context reporting. However, it is never used for target comparison, work queue ordering, or any decision-making. No code path references `target_verified_strict` or uses `verified_strict` to gate actions.

### 5. File path accuracy
**PARTIALLY INACCURATE.** The submission references:
- `engine/_state/merge_findings.py:180` — actual file is `desloppify/engine/_state/merge_issues.py:201`
- `engine/_scoring/policy/core.py:183-186` — actual location is `desloppify/engine/_scoring/policy/core.py:191-195`
- `engine/_state/resolution.py:97-103` — actual location is `desloppify/engine/_state/resolution.py:99-105`
- `app/commands/helpers/score.py:31` — this file does not exist; the actual target usage is in `score_update.py:62` and `next/cmd.py:213`

All conceptual references map to real code despite wrong paths/lines.

## Duplicate Check
- **S127** by the same author (@xliry, comment 4004890204) is a resubmission of the same finding with identical claims. S033 has priority as the earlier submission.
- **S152** by @mpoffizial covers a related but distinct angle: auto-resolve laundering where `wontfix`/`false_positive` penalties are erased when code changes cause issues to disappear. This is complementary, not duplicative — S033 focuses on the persistence of false_positive through rescans, S152 on status laundering via auto-resolve.

## Assessment
The core finding is valid and well-reasoned. The submission identifies a genuine design flaw where three independent code paths interact to create a score inflation vector:
1. No validation at resolution time
2. No reopening on rescan
3. Exclusion from the primary scoring mode

This contradicts the tool's stated goal that "the only way to improve the score is to actually make the code better." The fix would involve either: (a) reopening false_positive findings when re-detected by the same detector, or (b) including false_positive in strict scoring, or (c) adding validation at resolution time.
