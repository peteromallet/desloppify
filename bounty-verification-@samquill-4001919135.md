# Bounty Verification: S078 @samquill — Duplicate, Diverged CONFIDENCE_WEIGHTS

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4001919135
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. Canonical `CONFIDENCE_WEIGHTS` in `scoring_constants.py`
**CONFIRMED.** `base/scoring_constants.py` defines:
```python
CONFIDENCE_WEIGHTS = {Confidence.HIGH: 1.0, Confidence.MEDIUM: 0.7, Confidence.LOW: 0.3}
```
Module docstring: "Scoring constants shared across core and engine layers."

### 2. Batch `_CONFIDENCE_WEIGHTS` in `batch/scoring.py` (lines 8–12)
**CONFIRMED.** `app/commands/review/batch/scoring.py` defines:
```python
_CONFIDENCE_WEIGHTS = {
    "high": 1.2,
    "medium": 1.0,
    "low": 0.75,
}
```

### 3. Different values AND opposite semantics
**CONFIRMED.**
- Canonical: HIGH=1.0 is the ceiling — confidence dampens weight (low-confidence issues contribute less).
- Batch: high=1.2 exceeds 1.0 — confidence is a multiplier above baseline (high-confidence issues are boosted).
- These encode opposite assumptions about what "confidence" means for scoring.

### 4. `batch/scoring.py` never imports from `scoring_constants.py`
**CONFIRMED.** No import from `scoring_constants` exists in `batch/scoring.py`. The batch module independently defines its own version.

### 5. Five other files import the canonical version
**CONFIRMED.** At snapshot, the canonical `CONFIDENCE_WEIGHTS` is imported in:
- `base/output/issues.py` (line 10)
- `engine/_scoring/detection.py` (line 8)
- `engine/_scoring/policy/core.py` (line 11)
- `intelligence/review/_prepare/remediation_engine.py` (line 10)
- `tests/scoring/test_scoring.py` (line 12)

### 6. `DimensionMergeScorer.issue_severity()` uses batch weights for real scoring
**CONFIRMED.** `issue_severity()` at line ~71 uses `_CONFIDENCE_WEIGHTS.get(confidence, 1.0)` to compute per-issue severity, which feeds `issue_pressure_by_dimension()`, which feeds `score_dimension()` and `merge_scores()` — the final merged holistic review scores users see.

## Duplicate Check
- S029 (@xinlingfeiwu) is about `compute_score_impact` using flat 1.0 weight — a different function and different bug. Not a duplicate.
- No other submission in the inbox covers the batch/scoring.py diverged weights topic.

## Assessment
This is a strong finding. The submission correctly identifies that `batch/scoring.py` silently defines its own `_CONFIDENCE_WEIGHTS` with completely different values and opposite semantics from the canonical definition in `scoring_constants.py`. Five other files use the canonical definition, making `batch/scoring.py` the sole outlier.

This is not a theoretical concern — `DimensionMergeScorer.issue_severity()` directly uses these weights to compute the pressure adjustments that affect every holistic review score. A contributor updating the canonical weights (e.g., rebalancing confidence impact) would have no way to know the batch scorer silently ignores those changes.

The analysis is well-structured, the values are exactly correct, and the impact chain from weights → issue_severity → merged scores is accurately traced.
