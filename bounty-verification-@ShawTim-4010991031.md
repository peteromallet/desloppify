# Bounty Verification: S233 @ShawTim

## Submission

**Author:** @ShawTim
**ID:** S233 (comment 4010991031)
**Claim:** The 30% floor anti-gaming penalty in `scoring.py` is mathematically dead code. Because `build_investigation_batches` creates exactly one batch per dimension, `score_raw_by_dim` always contains a single score per dimension, making `min([score]) == score == weighted_mean`. The floor-aware blend `(0.7 * score) + (0.3 * score) = score` is always an identity function.

## Code Trace (at commit 6eb2065)

1. **`build_investigation_batches`** (`desloppify/intelligence/review/prepare_batches.py:296-324`): Docstring explicitly states "Build one batch per dimension from holistic context. Each batch has exactly one dimension and its relevant seed files." The `_DIMENSION_FILE_MAPPING` dict maps each dimension to exactly one collector; iteration produces one batch per dimension.

2. **`batch_concerns`** (`desloppify/intelligence/review/prepare_holistic_flow.py:267-280`): When concern signals exist for `design_coherence`, they are **merged into the existing batch** rather than creating a duplicate. This preserves the one-batch-per-dimension invariant.

3. **`_accumulate_batch_scores`** (`desloppify/app/commands/review/batch/core.py:535-536`):
   ```python
   score_buckets.setdefault(key, []).append((score_value, weight))
   score_raw_by_dim.setdefault(key, []).append(score_value)
   ```
   With one batch per dimension, each key gets exactly one entry.

4. **`merge_scores`** (`desloppify/app/commands/review/batch/scoring.py:143-165`):
   ```python
   weighted_mean = numerator / max(denominator, 1.0)  # = score (single entry)
   floor = min(score_raw_by_dim.get(key, [weighted_mean]))  # = min([score]) = score
   ```

5. **`score_dimension`** (`desloppify/app/commands/review/batch/scoring.py:113-117`):
   ```python
   floor_aware = _WEIGHTED_MEAN_BLEND * inputs.weighted_mean + _FLOOR_BLEND_WEIGHT * inputs.floor
   # = 0.7 * score + 0.3 * score = score
   ```

The entire floor mechanism (`_FLOOR_BLEND_WEIGHT = 0.3`, `_WEIGHTED_MEAN_BLEND = 0.7`) is an identity function in 100% of cases.

## Verdict: YES_WITH_CAVEATS

The finding is **correct and verified**: the floor anti-gaming mechanism is architecturally dead code. The one-batch-per-dimension design guarantees `floor == weighted_mean`, making the 30% floor blend a no-op.

**Caveats:**
- **Low practical impact:** The floor mechanism was intended to pull scores down when outlier batches exist. Since it never activates, scores are not incorrectly lowered — the effect is that the anti-gaming claim in the README is unsupported, not that scores are wrong.
- **Same author, third iteration:** ShawTim submitted S116 (floor exploitable via historical data — incorrect), S184 (floor exploitable via file merging — incorrect exploit, but the S184 verification independently discovered the identity-function property). S233 is the first submission that correctly identifies the **root cause** (one batch per dimension → identity function) as the primary finding.
- **Issue pressure still works:** The `score_dimension` method also applies `issue_penalty` and `issue_cap` adjustments. These mechanisms are independent of the floor blend and do function correctly.

## Scores

| Criterion | Score |
|-----------|-------|
| Significance | 5/10 |
| Originality | 4/10 |
| Core Impact | 4/10 |
| Overall | 4/10 |
