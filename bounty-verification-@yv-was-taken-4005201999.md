# Bounty Verification: S151 @yv-was-taken

## Submission
**Score Mode Semantic Incoherence: "Strictest" Mode Can Produce HIGHER Scores Than "Strict"**

## Code Trace (commit 6eb2065)

### Claim: `_aggregate_scores` passes only mechanical dims to verified_strict but all dims to strict
**state_integration.py:133-148** — Confirmed.

```python
def _aggregate_scores(dim_scores: dict) -> dict[str, float]:
    mechanical = {
        n: d for n, d in dim_scores.items()
        if "subjective_assessment" not in d.get("detectors", {})
    }
    return {
        "strict_score": compute_health_score(dim_scores, score_key="strict"),        # all dims
        "verified_strict_score": compute_health_score(mechanical, score_key="verified_strict_score"),  # mechanical only
    }
```

- `strict_score`: all dimensions (mechanical + subjective), strict failure statuses
- `verified_strict_score`: mechanical dimensions only, strictest failure statuses

### Claim: subjective dims get 60% weight, dragging strict_score down
**policy/core.py:146-147** — Confirmed.

```python
SUBJECTIVE_WEIGHT_FRACTION = 0.60
MECHANICAL_WEIGHT_FRACTION = 1.0 - SUBJECTIVE_WEIGHT_FRACTION  # = 0.40
```

### Claim: when subjective dims excluded, mechanical gets 100% weight
**health.py:111-114** — Confirmed.

```python
if subj_avg is None:
    mechanical_fraction = 1.0
    subjective_fraction = 0.0
```

When `compute_health_score` receives only mechanical dimensions (no subjective), `subj_avg` is `None`, so mechanical gets 100% weight instead of 40%.

### Claim: verified_strict can be higher than strict
**Confirmed via arithmetic.** With mechanical avg = 80 (strict) / 75 (verified_strict), subjective avg = 30:
- `strict_score = 80 × 0.4 + 30 × 0.6 = 50`
- `verified_strict_score = 75 × 1.0 = 75`

The "strictest" score (75) exceeds the "strict" score (50) by 50%.

### Line reference accuracy
- state_integration.py:133-148 → `_aggregate_scores` starts at line 133. Correct.
- health.py:108-125 → Pool averaging and fraction logic at lines 111-124. Correct (off by 3 on start).
- policy/core.py:146-147 → Weight fractions. Exact.
- policy/core.py:191-195 → FAILURE_STATUSES_BY_MODE at line 191. Exact.

## Duplicate Check
No prior submission identifies this specific score-mode inversion. Related but distinct:
- S124: shadow scoring pipeline (ScoreBundle discarded) — different issue
- S046: work queue uses lenient headroom for strict target — different optimization bug
- S155 (same author): unassessed subjective caps score at 40% — different manifestation of subjective weighting

## Caveats
1. **Naming vs invariant:** The submission assumes "verified_strict" implies "monotonically stricter than strict." The codebase doesn't document this invariant. "verified_strict" may be intentionally named as "strictest failure counting on mechanical dimensions" — a different axis, not a superset of "strict."
2. **Two independent axes are by design:** `objective_score` also excludes subjective dims. The system explicitly separates mechanical-only and full scoring. The combination of strictest failure counting + mechanical-only dimensions in `verified_strict` may be intentional, not accidental conflation.
3. **No user confusion evidence:** The submission doesn't cite user-facing output that displays these scores side-by-side or implies monotonic ordering. If users never compare them directly, the semantic incoherence has no practical impact.
4. **Fix is straightforward:** Either include subjective in verified_strict or document the non-monotonic relationship. Low effort to resolve.

## Verdict
**YES_WITH_CAVEATS** — The code analysis is accurate and the scenario is real. Verified_strict can genuinely exceed strict when subjective scores are low. However, the assumption that score modes must be monotonically ordered is a design judgment, not a proven invariant violation. The naming is confusing but the behavior may be intentional.
