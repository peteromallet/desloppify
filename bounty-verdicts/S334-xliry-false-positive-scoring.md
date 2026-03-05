# S334 Verdict: @xliry — false_positive Scoring Bypass

## Claim

`false_positive` findings bypass strict scoring and never reopen on rescan.
Three code paths interact: (1) `upsert_findings()` only reopens `fixed`/`auto_resolved`,
(2) `FAILURE_STATUSES_BY_MODE` excludes `false_positive` from strict failures,
(3) `verified_strict` includes it but is display-only.

## Duplicate Check

**This is a DUPLICATE of S25** by the same author (@xliry), titled "false_positive
scan-proof score inflation", which was already verified with scores
Sig=8, Orig=8, Core=9, Overall=8. S25 covers the same three code paths
(merge_findings.py:180, FAILURE_STATUSES_BY_MODE, verified_strict display-only)
with the same conclusion about false_positive being scan-proof and score-invisible.

## Verification

Despite being a duplicate, the claims are verified for completeness:

### VERIFIED: false_positive excluded from reopening

**`merge_findings.py:180`** — `upsert_findings()` only reopens findings with
status `fixed` or `auto_resolved`:
```python
if previous["status"] in ("fixed", "auto_resolved"):
```
A `false_positive` finding that reappears in detector output gets its metadata
updated (last_seen, tier, confidence, summary, detail) but status is preserved.
The submission's line reference (180) is accurate.

### VERIFIED: false_positive excluded from strict failure statuses

**`policy/core.py:191-195`**:
```python
FAILURE_STATUSES_BY_MODE: dict[ScoreMode, frozenset[str]] = {
    "lenient": frozenset({"open"}),
    "strict": frozenset({"open", "wontfix"}),
    "verified_strict": frozenset({"open", "wontfix", "fixed", "false_positive"}),
}
```
Submission claimed lines 183-186; actual location is 191-195 (off by ~8 lines).

### VERIFIED: verified_strict is display-only

The `target_strict_score` system (`score.py:31-39`, `score_update.py:62-63`,
`next.py:94`) and the `next` command queue (`next.py:171-196`) use `strict_score`,
not `verified_strict_score`. The verified_strict score appears in display only.

### PARTIALLY VERIFIED: resolve_issues accepts false_positive without validation

Submission refers to `resolve_findings()` at `resolution.py:97`. Actual function
is `resolve_issues()` at `resolution.py:99`. Wrong name, close line number.

## Accuracy

| Reference | Claimed | Actual | Match |
|-----------|---------|--------|-------|
| Function name | `resolve_findings()` | `resolve_issues()` | Wrong name |
| File: resolution.py | line 97 | line 99 | Close (off by 2) |
| merge_findings.py | line 180 | line 180 | Exact |
| policy/core.py | lines 183-186 | lines 191-195 | Off by ~8 lines |
| score.py | lines 31-39 | lines 31-39 | Exact |

## Scores

- **Significance: 5/10** — Real asymmetry, but duplicate of own prior submission.
- **Originality: 0/10** — Duplicate of S25 by the same author. No new findings.
- **Core Impact: 4/10** — Same impact as S25; affects gaming resistance but
  theoretical without validation bypass.
- **Overall: 2/10** — Verified claims but zero originality as a self-duplicate.

## Status: DUPLICATE

Duplicate of S25 by the same author (@xliry). All three claims (reopen guard,
strict scoring exclusion, verified_strict display-only) were already verified
and scored in S25. No new information in this submission.
