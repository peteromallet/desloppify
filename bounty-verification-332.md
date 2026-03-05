# Bounty Verification Report — S332

**Submission**: @Tib-Gridello — Heterogeneous tuple sort keys in `_natural_sort_key` cause TypeError and wrong ordering
**Verifier**: lota-1
**Date**: 2026-03-05

---

## Status: VERIFIED

All four claims are confirmed. The `_natural_sort_key` function returns tuples of different lengths for items at the same ranking tier (`_RANK_ISSUE`), leading to both a reproducible TypeError crash and semantically wrong cross-type ordering.

## Evidence

### Claim 1: Heterogeneous tuple lengths — CONFIRMED

At `ranking.py:222-227`, subjective items return a **4-element** tuple:
```python
(_RANK_ISSUE, -impact, subjective_score_value(item), item.get("id", ""))
```

At `ranking.py:231-238`, mechanical items return a **6-element** tuple:
```python
(_RANK_ISSUE, -impact, CONFIDENCE_ORDER.get(...), -review_weight, -count, item.get("id", ""))
```

Both share `_RANK_ISSUE` (value `1`) as element[0], so Python's tuple comparison proceeds to subsequent elements when items tie.

### Claim 2: TypeError crash — CONFIRMED

When `estimated_impact` ties (element[1] equal), element[2] is compared across types: `subjective_score_value` (float, range 0-100) vs `CONFIDENCE_ORDER` value (int, 0/1/2/9). If element[2] also ties (e.g., `subjective_score_value` returns `0.0` and confidence is `"high"` → `0`), element[3] compares `item.get("id", "")` (str) vs `-review_weight` (float). Python 3 raises `TypeError: '<' not supported between instances of 'str' and 'float'`.

This is reproducible when:
- Both items have equal `estimated_impact`
- A subjective item has `subjective_score_value` equal to a `CONFIDENCE_ORDER` value (0, 1, 2, or 9)

The `estimated_impact` is set to `0.0` for all items when `dimension_scores` is empty (`ranking.py:76-77`), making the tie condition common.

### Claim 3: Semantically wrong ordering — CONFIRMED

Element[2] cross-compares `subjective_score` (range 0-100) against `confidence_order` (range 0-9). Since `CONFIDENCE_ORDER` values max at 9 (`helpers.py:5`: `{"high": 0, "medium": 1, "low": 2}`, default 9), mechanical items with any confidence level will almost always sort before subjective items (whose scores range 0-100). This means the sort is not comparing like-for-like dimensions — it is comparing subjective quality scores against confidence tier ordinals.

### Claim 4: File paths and line numbers — ALL CORRECT

| Claim | Actual | Status |
|-------|--------|--------|
| `ranking.py:189-238` (`_natural_sort_key`) | Lines 189-238 | Exact match |
| `core.py:127` (`items.sort(key=item_sort_key)`) | Line 127 | Exact match |
| `ranking_output.py:68` (subjective ranking_factors) | Line 68 | Exact match |
| `ranking_output.py:87` (mechanical ranking_factors) | Line 87 | Exact match |
| `ranking.py:76-77` (`estimated_impact = 0.0`) | Lines 76-77 | Exact match |

### Additional context

- `ranking_output.py:68,87` documents the *intended* ranking factors differently for subjective vs mechanical items, but `_natural_sort_key` uses incompatible tuple structures to implement them, meaning the sort key disagrees with the documented policy.
- The call site at `core.py:127` (`items.sort(key=item_sort_key)`) wraps `_natural_sort_key`, so the bug affects every queue sort operation.

## Scores

| Dimension | Score | Rationale |
|-----------|-------|-----------|
| **Significance** | 7 | A sorting crash + wrong ordering in the primary work-queue ranking path is meaningful. Every `desloppify queue` invocation hits this code. |
| **Originality** | 8 | Deep analysis of tuple-comparison semantics across heterogeneous item types; non-obvious crash condition requiring multi-element tie. |
| **Core Impact** | 6 | Affects work-queue presentation order, which influences what issues users work on. Does not directly corrupt scores or gaming resistance, but misranking items undermines prioritization accuracy. |
| **Overall** | 7 | Strong, well-evidenced finding with exact file/line references, reproducible crash path, and clear semantic ordering bug. |
