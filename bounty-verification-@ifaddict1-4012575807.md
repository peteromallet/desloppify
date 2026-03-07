# Bounty Verification: S252 @ifaddict1

**Submission:** Disappeared Dimensions Are Carried Forward Forever and Permanently Pollute overall_score
**Comment ID:** 4012575807
**Snapshot commit:** 6eb2065

## Summary

The submission claims that when a mechanical dimension disappears between scans (detector removed, language changed, scan path narrowed), `_materialize_dimension_scores()` carries forward the stale dimension indefinitely, and `_aggregate_scores()` includes these ghost dimensions in `compute_health_score()`, permanently depressing `overall_score`.

## Verification

### Claim 1: `_materialize_dimension_scores()` carries forward stale dimensions forever

**VERIFIED** — `state_integration.py:197-213`:
```python
for dim_name, prev_data in prev_dim_scores.items():
    if dim_name in state["dimension_scores"]:
        continue
    if not isinstance(prev_data, dict):
        continue
    if "subjective_assessment" in prev_data.get("detectors", {}):
        continue
    carried = {**prev_data, "carried_forward": True}
    # ...
    state["dimension_scores"][dim_name] = carried
```
Non-subjective dimensions that disappeared from the current scan are injected back into `state["dimension_scores"]` with `carried_forward: True`. On subsequent recomputes, these carried-forward dimensions are still in `prev_dim_scores` (via `state.get("dimension_scores", {})`), so they are re-carried indefinitely.

### Claim 2: `_aggregate_scores()` includes ghost dimensions in score computation

**VERIFIED** — `state_integration.py:133-148`:
```python
def _aggregate_scores(dim_scores: dict) -> dict[str, float]:
    return {
        "overall_score": compute_health_score(dim_scores),
        # ...
    }
```
Called at line 233 via `state.update(_aggregate_scores(state["dimension_scores"]))`, this operates on the full dimension set including carried-forward ghosts. No filtering on `carried_forward` occurs.

### Claim 3: `carried_forward: True` flag is metadata-only for scoring

**VERIFIED** — `compute_health_breakdown()` in `results/health.py` iterates all dimension scores and computes weighted averages without any check for `carried_forward`. The flag IS used in the display layer at `app/commands/scan/reporting/dimensions.py:120` to show a "⟲ prior scan" suffix, but this is cosmetic only — the score computation is unaware of it.

### Claim 4: `compute_score_bundle()` correctly computes from current-scan dimensions only

**VERIFIED** — `results/core.py:104-137`: `compute_score_bundle()` builds dimension scores from `potentials` (current scan only) and computes aggregate scores from those. However, `_materialize_dimension_scores()` discards these bundle-level aggregates (as confirmed by S124) and replaces them with `_aggregate_scores()` output that includes carried-forward ghosts.

### Claim 5: Concrete scenario math

**VERIFIED** — 3 dimensions at 90.0 with weight 1.0 each = avg 90.0. Adding a ghost "File health" at 60.0 with `MECHANICAL_DIMENSION_WEIGHTS` weight 2.0: (90×3 + 60×2) / (3+2) = 78.0. The 12-point depression is correct (assuming all dimensions pass the `MIN_SAMPLE` threshold for full `sample_factor`).

## Duplicate Check

- **S124** (@openclawmara): Covers the shadow scoring pipeline divergence — ScoreBundle aggregates being discarded and replaced by `_aggregate_scores`. Verdict: YES_WITH_CAVEATS. S252 is related (both involve `_aggregate_scores` overwriting bundle results) but S252 focuses specifically on the **carry-forward persistence mechanism** and its impact on score contamination, which S124 does not address.
- **S253** (@lbbcym): Explicitly references S252 by @ifaddict1 and calls itself a "verification" of the same finding. S253 is a duplicate of S252, not the other way around.
- **S192** (@juzigu40-ui): About stale subjective assessments remaining score-authoritative — different mechanism (subjective vs mechanical carry-forward).

## Verdict

**YES** — All claims verified with accurate code references. The carry-forward loop in `_materialize_dimension_scores` persists stale mechanical dimensions indefinitely. These ghost dimensions are included in `_aggregate_scores` / `compute_health_score` without any filtering, discount, or expiration. The `carried_forward: True` flag is display-only metadata. The fix would be to either: (a) exclude `carried_forward` dimensions from score computation, (b) add a TTL/expiration mechanism, or (c) clear carried-forward dimensions when the scan configuration changes. Original finding — S124 covers the pipeline divergence but not the carry-forward persistence. S253 is a derivative of this submission.

## Scores

| Criterion | Score | Rationale |
|-----------|-------|-----------|
| Significance | 6 | Real score contamination — ghost dimensions permanently depress overall_score with no user-visible indication beyond a subtle display suffix |
| Originality | 6 | Not covered by S124 (which focuses on pipeline divergence). Carry-forward persistence is a distinct finding |
| Core Impact | 5 | Score inaccuracy is real but requires dimension disappearance (config/path change); the display layer does hint at carried-forward status |
| Overall | 6 | Well-documented finding with correct code references and concrete scenario. Real design flaw with no expiration mechanism |
