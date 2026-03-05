# Bounty Verification: @Tib-Gridello (comment #4004794411)

**Verdict date:** 2026-03-06
**Overall verdict:** VALID — both bugs confirmed

---

## Bug 1: TypeError crash from mismatched tuple lengths

**Claim:** `_natural_sort_key` in `ranking.py` returns tuples of different lengths for subjective vs mechanical items at the same `_RANK_ISSUE` tier, causing a `TypeError` when Python falls through to comparing incompatible types.

**Verification:**

Before fix, the subjective branch returned:
```python
(_RANK_ISSUE, -impact, subjective_score_value(item), item.get("id", ""))  # 4 elements
```

Mechanical returned:
```python
(_RANK_ISSUE, -impact, CONFIDENCE_ORDER.get(...), -review_weight, -count, item.get("id", ""))  # 6 elements
```

When `estimated_impact` tied, Python compared position [2]: `float` (subjective score) vs `int` (confidence rank) — comparing these is technically legal, but when those also tied, position [3] compared `str` (id) vs `float` (-review_weight), raising `TypeError: '<' not supported between instances of 'str' and 'float'`.

**Status:** CONFIRMED AND FIXED in commit `81f4b50`.

---

## Bug 2: Semantic cross-comparison of subjective_score_value vs CONFIDENCE_ORDER

**Claim:** Even with equal-length tuples, position [2] still holds semantically incompatible values — `subjective_score_value` (float 0–100) for subjective items vs `CONFIDENCE_ORDER.get(...)` (int 0–2) for mechanical items. This produces meaningless ordering when impact ties.

**Verification:**

After the Bug 1 fix, the subjective branch returned:
```python
(_RANK_ISSUE, -impact, subjective_score_value(item), 0.0, 0, item.get("id", ""))
```

Mechanical:
```python
(_RANK_ISSUE, -impact, CONFIDENCE_ORDER.get(..., 9), -review_weight, -count, item.get("id", ""))
```

At position [2], Python could compare e.g. `45.0` (a subjective score) against `0` (high-confidence mechanical), ordering the high-confidence mechanical item *after* a 45% subjective item — semantically wrong.

**Status:** CONFIRMED AND FIXED by adding an integer type-discriminator at position [2]:

```python
# Subjective lane (sorts before mechanical when impact ties)
(_RANK_ISSUE, -impact, 0, subjective_score_value(item), 0.0, 0, id)

# Mechanical lane
(_RANK_ISSUE, -impact, 1, CONFIDENCE_ORDER.get(..., 9), -review_weight, -count, id)
```

The discriminator ensures subjective and mechanical items compare only within their own lane. The discriminator value (0 < 1) means subjective items sort before mechanical items when impact is equal, which preserves the intent that unresolved subjective dimensions are higher-priority.

---

## Files changed

- `desloppify/engine/_work_queue/ranking.py` — Bug 2 fix (type-discriminator at position [2])

## Bounty decision

Both bugs are valid. @Tib-Gridello's submission earns the bounty for:
- Identifying the root TypeError crash (Bug 1) — already fixed pre-verification
- Identifying the semantic cross-comparison flaw (Bug 2) — fixed in this PR
