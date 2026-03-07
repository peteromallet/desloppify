# Bounty Verification: S125 @Tib-Gridello — Work Queue Sort Key Crash

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4004794411
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. Heterogeneous tuple lengths in `_natural_sort_key`
**CONFIRMED.** At `ranking.py:219-237` (snapshot), subjective items return a 4-element tuple:
```python
return (_RANK_ISSUE, -impact, subjective_score_value(item), item.get("id", ""))
```
Mechanical items return a 6-element tuple:
```python
return (_RANK_ISSUE, -impact, CONFIDENCE_ORDER.get(...), -review_weight, -count, item.get("id", ""))
```
Both use `_RANK_ISSUE` (1) as the first element.

### 2. TypeError crash when element[2] ties
**CONFIRMED.** `subjective_score_value()` returns a float (from `ranking_output.py:11-22`). `CONFIDENCE_ORDER` maps to `{"high": 0, "medium": 1, "low": 2}` (from `planning/helpers.py`). When both impact and element[2] tie (e.g., `subjective_score=0.0` matching `CONFIDENCE_ORDER["high"]=0`), Python advances to element[3]: `str` (id) vs `float` (-review_weight). This raises `TypeError: '<' not supported between instances of 'str' and 'float'`.

### 3. Equal impact ties are common
**CONFIRMED.** `enrich_with_impact()` at `ranking.py:73-77` sets `estimated_impact=0.0` for all items when `dimension_scores` is empty. This makes all items tie on element[1], forcing comparison to element[2].

### 4. Semantically wrong ordering (Bug 2)
**CONFIRMED.** When the crash doesn't occur, element[2] cross-compares `subjective_score_value` (range 0-100) against `CONFIDENCE_ORDER` values (range 0-2). Since 0-2 < virtually any non-zero subjective score, mechanical items always sort before subjective ones at equal impact. The `item_explain` function in `ranking_output.py:68,87` documents these as independent ranking factors (`subjective_score asc` vs `confidence asc`), confirming the code contradicts its specification.

### 5. Sort invocation at core.py:127
**CONFIRMED.** `core.py:127` calls `items.sort(key=item_sort_key)`, which delegates to `_natural_sort_key` for non-plan items.

## Duplicate Check

No prior submissions address `_natural_sort_key` heterogeneous tuples or the sort key crash. This is an original finding.

## Verdict

| Question | Answer | Reasoning |
|----------|--------|-----------|
| **Is this poor engineering?** | YES | Mixing tuple lengths in a sort key is a correctness bug that crashes at runtime. |
| **Is this at least somewhat significant?** | YES | Affects every `desloppify next` invocation; crashes or silently mis-prioritizes work items. |

**Final verdict:** YES

Both bugs are real and independently impactful. Bug 1 is a crash-causing defect triggered by realistic data conditions. Bug 2 silently corrupts queue ordering, undermining the 60% subjective weight in scoring.

## Scores

| Criterion | Score |
|-----------|-------|
| Significance | 7/10 |
| Originality | 8/10 |
| Core Impact | 7/10 |
| Overall | 7/10 |

## Why Desloppify Missed This

- **What should catch:** A type checker or test with mixed subjective/mechanical items at equal impact
- **Why not caught:** No test exercises sorting with heterogeneous item types at the same rank tier with tied impact values
- **What could catch:** A unit test that sorts a list containing both subjective and mechanical items with `estimated_impact=0.0`, or a mypy-strict check enforcing consistent tuple return types
