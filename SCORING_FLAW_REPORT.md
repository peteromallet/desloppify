# Scoring Floor Logic Allows "Outlier Masking" via File Merging

While the `floor` mechanism in `desloppify/app/commands/review/batch/scoring.py` is intended to be an anti-gaming feature (preventing high averages from masking outliers), its implementation using `min(score_raw_by_dim)` introduces a direct gaming vector.

## The Intended Mechanism

The final score blends a 70% weighted mean with a 30% "floor" (the lowest-scoring file in the current scan batch):

```python
floor = min(score_raw_by_dim.get(key, [weighted_mean]))
floor_aware = _WEIGHTED_MEAN_BLEND * inputs.weighted_mean + _FLOOR_BLEND_WEIGHT * inputs.floor
```

If a developer has 10 great files and 1 terrible file, the 1 terrible file acts as an anchor, dragging the `floor_aware` score down by a massive 30%. This is *intended* to force the developer to fix the terrible file.

## The Gaming Exploit

Because the floor is strictly the minimum file score in the batch, a lazy developer can completely bypass this penalty **without fixing any code**—simply by copying the contents of the terrible file and appending them to their largest, highest-scoring file.

### Mathematical Proof

Consider a dimension where weights equal lines of code (LOC):
- **File A (Clean):** Score 100, Weight 1000
- **File B (Terrible):** Score 0, Weight 100

**Before Gaming (Two Files):**
- Weighted Mean: `(1000*100 + 100*0) / 1100` = **90.9**
- Floor (Minimum file score): `min(100, 0)` = **0**
- Final `floor_aware` score: `(0.7 * 90.9) + (0.3 * 0)` = **63.6**

The developer's score is a failing 63.6. 

**After Gaming (Merged into One File):**
The developer appends File B to the bottom of File A.
- **File AB (Merged):** Score 90.9, Weight 1100
- Weighted Mean: `(1100*90.9) / 1100` = **90.9**
- Floor (Minimum file score): `min(90.9)` = **90.9**
- Final `floor_aware` score: `(0.7 * 90.9) + (0.3 * 90.9)` = **90.9**

The score jumps from **63.6 to 90.9**, an increase of 27.3 points, while the exact same sloppy code remains in the codebase. This directly violates the README's core promise that "the scoring resists gaming."

## Suggested Fix

To truly resist gaming, the floor should not be determined by arbitrary file boundaries. Instead, it should be calculated using a percentile-based anchor of the total weight (e.g., the average score of the bottom 10% of the codebase by weight).

```python
# Conceptual fix
sorted_files = sort_by_score(weighted_scores)
bottom_10_percent = take_bottom_weight(sorted_files, total_weight * 0.1)
floor = compute_weighted_mean(bottom_10_percent)
```

This ensures that bad code always penalizes the score proportionally, regardless of whether it's isolated in a small file or hidden inside a monolith.

## Files Checked

- `desloppify/app/commands/review/batch/scoring.py` (lines 155-173)

---

**Reporter:** ShawTim  
**Date:** March 2026  
**Bounty Issue:** #204