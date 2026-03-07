# Bounty Verification: S029 @xinlingfeiwu — compute_score_impact Ignores Confidence Weights

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4001399191
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `compute_score_impact()` uses flat `1.0` weight per issue
**CONFIRMED.** `desloppify/engine/_scoring/results/impact.py:41`:
```python
new_weighted = max(0.0, old_weighted - issues_to_fix * 1.0)
```

### 2. Scoring pipeline uses variable confidence weights
**CONFIRMED.** `desloppify/engine/_scoring/detection.py:57`:
```python
return CONFIDENCE_WEIGHTS.get(issue.get("confidence", "medium"), 0.7)
```
Where `CONFIDENCE_WEIGHTS` from `desloppify/base/scoring_constants.py:7`:
```python
CONFIDENCE_WEIGHTS = {Confidence.HIGH: 1.0, Confidence.MEDIUM: 0.7, Confidence.LOW: 0.3}
```

### 3. Error magnitudes in the table
**CONFIRMED.**
- HIGH: 1.0 simulated vs 1.0 actual = 0% error
- MEDIUM: 1.0 simulated vs 0.7 actual = +43% overestimate
- LOW: 1.0 simulated vs 0.3 actual = +233% overestimate

### 4. Test suite only exercises HIGH-confidence path
**CONFIRMED.** `tests/scoring/test_scoring.py:730` sets `weighted_failures: 40.0` for `failing: 40` issues, implying weight = 1.0 per issue. No test varies confidence weights.

### 5. Impact on user-facing features
**CONFIRMED.** `compute_score_impact` is called from:
- `app/commands/next/render.py:170,181` — `desloppify next` "+X pts" forecasts
- `app/commands/status/render.py` — `desloppify status`
- `intelligence/narrative/action_engine.py:59` — AI narrative engine
- `intelligence/narrative/dimensions.py` — dimension narratives

### 6. Proposed fix
The suggested fix (`avg_weight = old_weighted / max(1, det_data["failing"])`) is correct and O(1). The `det_data` dict already contains both `weighted_failures` and `failing`, so the average weight per issue can be derived without iterating over individual issues.

## Duplicate Check
No other submissions in the bounty pool target this specific function or the confidence weight mismatch in impact simulation.

## Assessment
This is a genuine bug, not a design trade-off. The impact simulation function and the scoring pipeline use inconsistent weight models, causing systematically inflated score forecasts for non-HIGH-confidence issues. The fix is simple and non-breaking. The submission accurately identifies the root cause, quantifies the error, and proposes a correct fix.
