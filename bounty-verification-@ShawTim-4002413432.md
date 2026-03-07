# Bounty Verification: S116 @ShawTim — Floor Blending Gaming Claim

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4002413432
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `_FLOOR_BLEND_WEIGHT = 0.3` in scoring.py allows gaming
**INCORRECT.** The constant exists at `app/commands/review/batch/scoring.py:27`, but the claim about what it does is wrong.

The submission asserts the floor blending "uses historical data" so "a developer can coast on old cleanliness." In reality, the `floor` input is computed at `scoring.py:163` as:
```python
floor = min(score_raw_by_dim.get(key, [weighted_mean]))
```
This is the **minimum** raw score from the **current** review's batch results, populated during the active merge process (`merge.py:141-155`). It is not historical data.

### 2. Score is "artificially inflated to a passing grade"
**INCORRECT.** The blending formula is:
```python
floor_aware = 0.7 * weighted_mean + 0.3 * floor
```
Since `floor = min(raw_scores)` and `weighted_mean >= floor` by definition, the floor blend always **lowers** the score compared to using the weighted mean alone. This is a conservative, anti-gaming mechanism — it ensures the worst-performing batch gets 30% weight in the final score.

### 3. Critical bugs can still score high
**INCORRECT.** The scoring engine has multiple layers of protection beyond floor blending:
- Issue pressure penalties up to `_MAX_ISSUE_PENALTY = 24.0` (`scoring.py:32`)
- Extra penalties per additional issue: `_EXTRA_ISSUE_PENALTY = 0.8` (`scoring.py:38`)
- Hard issue-based score caps: `_CAP_FLOOR = 60.0`, `_CAP_CEILING = 90.0` (`scoring.py:41-42`)
- Pressure multiplier `_CAP_PRESSURE_MULTIPLIER = 3.5` (`scoring.py:43`)

Any codebase with critical issues would have its score capped and penalized regardless of the floor blend.

### 4. PR #232 referenced
PR #232 exists on the upstream repo but its body repeats the same incorrect claim about "historical cleanliness" without demonstrating an actual gaming vector. No proof-of-concept showing a gamed score is provided.

## Duplicate Check
No prior submissions cover floor blending in the batch scoring system.

## Assessment
The submission is based on a fundamental misunderstanding of the code. The author assumed `floor` refers to historical scores, but it is actually the minimum score from the current review's batch results. The floor blend is an anti-gaming measure (it pulls scores down), not a gaming vector. The claim is the opposite of what the code does.
