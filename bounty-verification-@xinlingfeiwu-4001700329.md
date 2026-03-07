# Bounty Verification: S046 @xinlingfeiwu

**Issue:** https://github.com/peteromallet/desloppify/issues/204
**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4001700329
**Author:** @xinlingfeiwu

## Problem (in our own words)

The `desloppify next` command displays and targets `strict_score`, but the work queue prioritization engine (`enrich_with_impact`) computes dimension headroom using the lenient score instead. This means the ranking of which issues to fix first is optimized against the wrong metric — dimensions with high lenient/low strict divergence are systematically mis-prioritized.

## Evidence

- **`ranking.py:80`** — `compute_health_breakdown(dimension_scores)` called without `score_key="strict"`, confirmed at exactly line 80.
- **`health.py:53`** — `score_key: str = "score"` default parameter, confirmed at exactly line 53.
- **`health.py:74`** — `score = float(data.get(score_key, data.get("score", 0.0)))` reads `"score"` (lenient) by default.
- **`state_integration.py:202-204`** — dimension_scores stores three values: `score` (lenient), `strict`, `verified_strict_score`. All three line numbers exact.
- **`state_integration.py:142`** — `compute_health_score(dim_scores, score_key="strict")` proves the parameter exists and works. Line number exact.
- **`next/cmd.py:298`** — `strict_score = state_mod.score_snapshot(state).strict` — the UI optimizes for strict. Line number exact.
- **`next/cmd.py:213`** — `target_strict = target_strict_score_from_config(config)` — target is strict.

## Fix

Pass `score_key="strict"` at `ranking.py:80`:
```python
breakdown = compute_health_breakdown(dimension_scores, score_key="strict")
```

## Verdict

| Question | Answer | Reasoning |
|----------|--------|-----------|
| **Is this poor engineering?** | YES | The optimization objective (lenient headroom) contradicts the stated target metric (strict_score), causing silent mis-prioritization. |
| **Is this at least somewhat significant?** | YES | Every `desloppify next` call ranks the entire work queue against the wrong objective function, potentially leading users to fix low-value issues first. |

**Final verdict:** YES

## Scores

| Criterion | Score |
|-----------|-------|
| Significance | 7/10 |
| Originality | 7/10 |
| Core Impact | 7/10 |
| Overall | 7/10 |

## Summary

This is a verified, well-researched bug with exact line-number references throughout. The submission correctly identifies a semantic mismatch: `enrich_with_impact` computes headroom from lenient scores while the user-facing target is `strict_score`. The analysis correctly shows the `score_key` parameter already exists and is used correctly elsewhere (`state_integration.py:142`), making this a clear oversight with a one-line fix.

## Why Desloppify Missed This

- **What should catch:** A cross-function consistency checker that verifies score_key usage is consistent between the scoring aggregation path and the prioritization path.
- **Why not caught:** The code is split across multiple modules (ranking, health, state_integration, next/cmd), and the default parameter value silently selects the wrong metric without any error.
- **What could catch:** An integration test asserting that work queue rankings change when strict vs lenient scores diverge, or a static analysis rule flagging `compute_health_breakdown` calls without explicit `score_key`.

## Verdict Files

- [Verdict JSON](https://github.com/xliry/desloppify/blob/fix/bounty-4001700329-xinlingfeiwu/bounty-verdicts/%40xinlingfeiwu-4001700329.json)
- [Verdict Report](https://github.com/xliry/desloppify/blob/fix/bounty-4001700329-xinlingfeiwu/bounty-verification-%40xinlingfeiwu-4001700329.md)

Generated with [Lota](https://github.com/xliry/lota)
