# Bounty Verification: shanpenghui — comment 4003909095

**Submitter:** @shanpenghui
**Comment ID:** 4003909095
**Verdict:** YES (VERIFIED)
**Scores:** Sig 4 / Orig 4 / Core 1 / Overall 3
**Date:** 2026-03-06

---

## Problem Restatement (Independent)

The submission claims that two contradictory `action-priority` dictionaries exist in the codebase: one in `desloppify/engine/_work_queue/helpers.py` and one in `desloppify/base/registry.py`. The claimed conflict: `helpers.py` ranks `refactor` higher priority than `reorganize`, while `registry.py` ranks `reorganize` higher than `refactor`.

My independent code trace confirms all claims, and additionally identifies a third table the submission missed.

---

## Claim Verification

### Claim 1: helpers.py defines ACTION_TYPE_PRIORITY with refactor(1) > reorganize(3) — CONFIRMED

**Evidence:**

```python
# desloppify/engine/_work_queue/helpers.py:15
ACTION_TYPE_PRIORITY = {"auto_fix": 0, "refactor": 1, "manual_fix": 2, "reorganize": 3}
```

This dict is used by `ranking.py` (imported at line 13) as the sort key for clusters:

```python
# desloppify/engine/_work_queue/ranking.py:209-216
action_pri = ACTION_TYPE_PRIORITY.get(
    item.get("action_type", "manual_fix"), 3
)
return (
    _RANK_CLUSTER,
    action_pri,
    -int(item.get("member_count", 0)),
    item.get("id", ""),
)
```

With lower values = higher priority: `auto_fix(0) > refactor(1) > manual_fix(2) > reorganize(3)`.

---

### Claim 2: base/registry.py _ACTION_PRIORITY has reorganize(1) > refactor(2) — CONFIRMED

**Evidence:**

```python
# desloppify/base/registry.py:455
_ACTION_PRIORITY = {"auto_fix": 0, "reorganize": 1, "refactor": 2, "manual_fix": 3}
```

This is used exclusively by `dimension_action_type()` to select the label for a dimension's best action type:

```python
# base/registry.py:464-474
def dimension_action_type(dim_name: str) -> str:
    best = "manual"
    best_pri = 99
    for d in _RUNTIME.detectors.values():
        if d.dimension == dim_name:
            pri = _ACTION_PRIORITY.get(d.action_type, 99)
            if pri < best_pri:
                ...
```

With lower values = higher priority: `auto_fix(0) > reorganize(1) > refactor(2) > manual_fix(3)`.

**Conflicts vs helpers.py:**
- `refactor`: helpers.py=1, base/registry.py=2 (priority inverted relative to reorganize)
- `reorganize`: helpers.py=3, base/registry.py=1 (priority inverted)
- `manual_fix`: helpers.py=2, base/registry.py=3 (different position)

---

### Claim 3 (not in submission): core/registry.py has a third conflicting table

**Evidence:**

```python
# desloppify/core/registry.py:360
_ACTION_PRIORITY = {"auto_fix": 0, "reorganize": 1, "refactor": 2, "manual_fix": 3}
```

Identical to `base/registry.py` in ordering, but a fully duplicated definition with no shared source. Also conflicts with `helpers.py`.

Additionally, `core/registry.py` has `_ACTION_LABELS = {"auto_fix": "fix", ...}` while `base/registry.py` has `_ACTION_LABELS = {"auto_fix": "autofix", ...}` — the label for `auto_fix` diverges between the two registry files.

---

## Summary Table

| File | auto_fix | reorganize | refactor | manual_fix |
|------|----------|------------|---------|------------|
| `helpers.py:15` | 0 | **3** | **1** | 2 |
| `base/registry.py:455` | 0 | **1** | **2** | 3 |
| `core/registry.py:360` | 0 | **1** | **2** | 3 |

The `helpers.py` ordering is the outlier. The two registry files agree with each other but contradict `helpers.py` on all three non-auto_fix entries.

---

## Impact

- **Work queue cluster sort order** (`ranking.py`): uses helpers.py ordering → clusters are sorted refactor > reorganize
- **Dimension action label** (`dimension_action_type()`): uses registry ordering → dimensions prefer reorganize > refactor
- **No scoring engine impact**: priority tables affect display ordering and label selection only; they do not influence score computation
- **Maintainability**: any future change to action priority must be applied in three separate files with no enforcement that they stay in sync

---

## Fix

**Strategy:** Expose `ACTION_TYPE_PRIORITY` as a public name from `base/registry.py` (canonical source), fix the ordering to match the registry consensus (`reorganize=1, refactor=2, manual_fix=3`), and have `helpers.py` and `core/registry.py` import it.

**Files changed:**

1. `desloppify/base/registry.py`: rename `_ACTION_PRIORITY` → `ACTION_TYPE_PRIORITY` (public)
2. `desloppify/engine/_work_queue/helpers.py`: remove local definition, import `ACTION_TYPE_PRIORITY` from `desloppify.base.registry`
3. `desloppify/core/registry.py`: remove local `_ACTION_PRIORITY`, import `ACTION_TYPE_PRIORITY` from `desloppify.base.registry`

**Canonical ordering adopted:** `{"auto_fix": 0, "reorganize": 1, "refactor": 2, "manual_fix": 3}` — matches the two-file consensus from both registry files.

---

## Files Examined

- `desloppify/engine/_work_queue/helpers.py` — `ACTION_TYPE_PRIORITY` definition at line 15
- `desloppify/base/registry.py` — `_ACTION_PRIORITY` at line 455, `dimension_action_type()` at lines 464–474
- `desloppify/core/registry.py` — `_ACTION_PRIORITY` at line 360, `dimension_action_type()` at lines 369–379
- `desloppify/engine/_work_queue/ranking.py` — `ACTION_TYPE_PRIORITY` usage at lines 209–216
