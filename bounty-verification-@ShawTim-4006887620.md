# Bounty Verification: S184 @ShawTim

## Submission

**Author:** @ShawTim
**ID:** S184 (comment 4006887620)
**Claim:** The floor blending mechanism (`_FLOOR_BLEND_WEIGHT = 0.3`) in the scoring engine can be gamed by merging a low-scoring file into a large high-scoring file, bypassing the floor penalty and inflating the final score by up to 27.3 points.

## Code Trace

### What the submission identifies correctly

1. **`_FLOOR_BLEND_WEIGHT = 0.3`** exists at `desloppify/app/commands/review/batch/scoring.py:28`
2. **`floor = min(score_raw_by_dim.get(key, [weighted_mean]))`** at line 163 — correctly identified
3. **Floor-aware formula:** `floor_aware = 0.7 * weighted_mean + 0.3 * floor` at lines 115-117
4. **Mathematical proof:** The arithmetic (before: 63.6, after merge: 90.9, delta: 27.3) is valid **in a hypothetical multi-batch scenario**

### Why the exploit does not work in practice

1. **One batch per dimension:** `desloppify/intelligence/review/prepare_batches.py` explicitly documents:
   > "Each batch builder returns exactly ONE batch with exactly ONE dimension."

2. **Consequence:** `score_raw_by_dim[key]` always contains exactly ONE element. Therefore:
   - `floor = min([single_score]) = single_score`
   - `weighted_mean = single_score` (only one score to average)
   - `floor_aware = 0.7 * x + 0.3 * x = x` — an identity function

3. **Batches are per-dimension, not per-file:** The submission assumes scores correspond to individual files, but the batch scoring system groups by dimension. Merging source files does not change how batches are formed.

4. **Same mechanism as S116:** Both S116 and S184 (same author) target `_FLOOR_BLEND_WEIGHT` in the batch scoring system. S116 incorrectly claimed "historical data" coasting; S184 more accurately describes the floor formula but proposes an equally non-viable attack vector.

## Verdict: NO

The submission demonstrates good understanding of the floor blending formula and provides correct theoretical math. However, the exploit is not practically viable because the architecture always produces exactly one batch per dimension, rendering `floor == weighted_mean` in all cases. The floor blend is effectively an identity function — it cannot be gamed because it has no effect. The file-merging attack vector is irrelevant to how batches are actually constructed.
