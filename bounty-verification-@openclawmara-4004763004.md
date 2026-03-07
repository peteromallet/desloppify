# Bounty Verification: S124 @openclawmara

**Submission:** Shadow Scoring Pipeline — ScoreBundle computes aggregate scores that are silently discarded and replaced by a divergent recalculation

**Snapshot:** `6eb2065`

## Claims Verified

### 1. ScoreBundle aggregates are dead computation — TRUE

`compute_score_bundle()` (`results/core.py:104-137`) returns a `ScoreBundle` with four aggregate fields: `overall_score`, `objective_score`, `strict_score`, `verified_strict_score`.

In production, `_update_objective_health()` (`state_integration.py:230`) passes the bundle to `_materialize_dimension_scores()`, which only reads per-dimension data (`bundle.dimension_scores`, `bundle.strict_dimension_scores`, `bundle.verified_strict_dimension_scores`). The four aggregate fields are never accessed.

Then `_aggregate_scores()` (`state_integration.py:133-148`) recomputes all four aggregates from the materialized `state["dimension_scores"]` dict, overwriting via `state.update()`.

Confirmed via `git grep`: bundle aggregate fields are only accessed in `tests/scoring/test_scoring.py`, never in production code.

### 2. Semantic divergence in verified_strict_score — TRUE

**Pipeline 1 (dead):** `compute_score_bundle()` at line 137:
```python
verified_strict_score=compute_health_score(verified_strict_scores)
```
Uses ALL dimensions (mechanical + subjective) from the verified_strict mode.

**Pipeline 2 (live):** `_aggregate_scores()` at line 144:
```python
"verified_strict_score": compute_health_score(mechanical, score_key="verified_strict_score")
```
Filters to `mechanical` dimensions only (excludes subjective).

Since `SUBJECTIVE_WEIGHT_FRACTION = 0.60` (confirmed at `policy/core.py:146`), Pipeline 1 would blend 60% subjective weight into verified_strict. Pipeline 2 uses 100% mechanical weight.

### 3. bundle fields never read — MOSTLY TRUE

`bundle.overall_score`, `.objective_score`, `.strict_score`, `.verified_strict_score` are read in `test_scoring.py` (lines 532-544) but never in production code.

### 4. Maintenance trap — TRUE

A developer fixing scoring logic in `compute_score_bundle` would see no production effect. The actual aggregate scores come from `_aggregate_scores()` in a different module with different dimension-inclusion rules.

## Verdict: YES_WITH_CAVEATS

The finding is structurally correct: dead aggregate computation, semantic divergence between pipelines, and a genuine maintenance trap. However:

- The dead aggregates cause **no production bug** since they're never used
- The semantic divergence is moot in practice (Pipeline 1 output is discarded)
- The fix is straightforward: remove the aggregate fields from ScoreBundle, or inline the per-dimension extraction without computing unused aggregates

Related to S151 (same `_aggregate_scores` function, different angle — S151 focuses on monotonicity invariant violation). Not a duplicate: S124 identifies the dead code/shadow pipeline, S151 identifies the consequence of the live pipeline's dimension-exclusion design.
