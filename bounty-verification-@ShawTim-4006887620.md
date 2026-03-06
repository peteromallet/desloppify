# Bounty Verification: @ShawTim submission #4006887620

**Scoreboard ID:** S338
**Verdict:** NO
**Date:** 2026-03-06

## Submission Summary

The submission claims that `floor = min(score_raw_by_dim)` at `scoring.py:163` can be gamed by physically merging a low-quality file into a large high-quality file. The claimed effect: the floor rises 27.3 points with no actual code improvement.

## Code References Examined

- `desloppify/app/commands/review/batch/scoring.py:163` — `floor = min(score_raw_by_dim.get(key, [weighted_mean]))`
- `desloppify/app/commands/review/batch/core.py:481-499` — `assessment_weight()` function
- `desloppify/app/commands/review/batch/core.py:514-536` — `_accumulate_batch_scores()`

## Claim Analysis

### Claim 1: The floor can be raised by merging files

**Status: PARTIALLY REAL, WRONG PROOF**

The underlying mechanism is real: `scoring.py:163` computes:

```python
floor = min(score_raw_by_dim.get(key, [weighted_mean]))
```

This is the minimum raw score across all review batches for a dimension. Two files reviewed in separate batches with scores `[100, 0]` produce `floor=0`. If merged into one file and reviewed together, the LLM might score the combined file at ~90, yielding `floor=90`.

The batch-granularity gaming vector exists as a design tradeoff.

**However, the proof is wrong.** The submission calculates the 27.3-point gain using LOC-based weighting:

> "1000 LOC high-quality / 100 LOC low-quality = 10x weighting leverage"

The actual `assessment_weight()` function at `core.py:481-499` does not use LOC:

```python
def assessment_weight(*, dimension, issues, dimension_notes) -> float:
    note = dimension_notes.get(dimension, {})
    note_evidence = len(note.get("evidence", [])) if isinstance(note, dict) else 0
    issue_count = sum(1 for issue in issues if str(issue.get("dimension", "")).strip() == dimension)
    return float(1 + note_evidence + issue_count)
```

Weight = `1 + evidence_count + issue_count`. File size (LOC) is not a factor anywhere in the weighting logic.

### Claim 2: 27.3-point floor gain from merging

**Status: UNVERIFIABLE**

The arithmetic proof depends entirely on the incorrect LOC-weighting assumption. The actual floor change from merging would depend on:
- How the LLM scores the combined file's content
- How many issues the LLM generates for the merged file
- How much evidence is cited in dimension notes

None of these are predictable from file size alone. The 27.3-point figure cannot be verified against real code.

### Claim 3: No countermeasures against file merging

**Status: INCORRECT**

File merging triggers at least two existing detectors:
- **gods.py** — flags large monolithic files
- **large.py** — flags files exceeding size thresholds

These detectors would generate issues for the merged file. Additional issues increase `issue_count` in `assessment_weight()`, which increases the merged batch's weight — but also increases `issue_pressure` which pulls the final score down via `score_dimension()`. The submission does not account for this detector interaction.

## Verdict: NO

The specific mathematical proof is invalid because it applies LOC-based weighting to a system that uses evidence+issue-count weighting. The 27.3-point gain cannot be reproduced against the actual code.

The underlying batch-granularity concern (file organization affects review batching, which affects floor scores) is a real design tradeoff, not a bug. The README anti-gaming guidance explicitly targets suppression, status laundering, and trivial fixes — file restructuring is a known scope limitation of batch-level review, not an implementation deficiency.

## Scores

| Dimension | Score |
|-----------|-------|
| Signal (significance) | 3/10 |
| Originality | 3/10 |
| Core Impact | 1/10 |
| Overall | 2/10 |
