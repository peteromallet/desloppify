# Bounty Verification: @ShawTim submission #4002413432

**Scoreboard ID:** S322
**Verdict:** NO
**Date:** 2026-03-06

## Submission Summary

The submission claims that `_FLOOR_BLEND_WEIGHT = 0.3` in `scoring.py` enables gaming by incorporating historical data into the floor score, allowing bad actors to pre-seed favorable historical state to inflate future scores.

## Code References Examined

- `desloppify/app/commands/review/batch/scoring.py:27` — `_FLOOR_BLEND_WEIGHT = 0.3`
- `desloppify/app/commands/review/batch/scoring.py:115-118` — `score_dimension()` blend formula
- `desloppify/app/commands/review/batch/scoring.py:163` — `floor = min(score_raw_by_dim.get(key, [weighted_mean]))`

## Claim Analysis

### Claim 1: _FLOOR_BLEND_WEIGHT incorporates historical data

**Status: FACTUALLY WRONG PREMISE**

The submission asserts the floor score is derived from historical data. The actual code at `scoring.py:163`:

```python
floor = min(score_raw_by_dim.get(key, [weighted_mean]))
```

`score_raw_by_dim` is a parameter passed into `merge_scores()`:

```python
def merge_scores(
    self,
    score_buckets: dict[str, list[tuple[float, float]]],
    score_raw_by_dim: dict[str, list[float]],
    issue_pressure_by_dim: dict[str, float],
    issue_count_by_dim: dict[str, int],
) -> dict[str, float]:
```

This dict contains raw scores from the **current batch only**. There is no historical state read anywhere in this function. The floor is the minimum score across dimensions in the current batch run — not from any prior execution.

### Claim 2: The 30% floor blend allows score inflation

**Status: INCORRECT**

The blend formula in `score_dimension()` (`scoring.py:115-118`):

```python
floor_aware = (
    _WEIGHTED_MEAN_BLEND * inputs.weighted_mean
    + _FLOOR_BLEND_WEIGHT * inputs.floor
)
```

`floor` is `min(score_raw_by_dim...)` — the **minimum** (worst) score in the batch. Blending 30% of the minimum score into the result pulls `floor_aware` **down** relative to the weighted mean alone. This is an anti-gaming mechanism: it prevents the weighted mean from being the sole determinant and anchors the merged score toward the worst-performing batch dimension.

An actor cannot use this to inflate scores — introducing any low-scoring material into the batch can only decrease the floor, which decreases `floor_aware`, which decreases the final score.

## Verdict: NO

The submission's central premise is factually wrong. The floor is computed from current-batch scores only (`scoring.py:163`), not from historical state. No historical data enters the computation. The `_FLOOR_BLEND_WEIGHT = 0.3` blend is anti-gaming by design: it anchors the merged score toward the batch minimum, making it harder to achieve high scores when any dimension scores poorly.

## Scores

| Dimension | Score |
|-----------|-------|
| Signal (significance) | 2/10 |
| Originality | 2/10 |
| Core Impact | 1/10 |
| Overall | 2/10 |
