# Bounty Verification: S181 @1553401156-spec

**Submission:** Global State Anti-Pattern in Registry
**File:** `desloppify/base/registry.py`
**Commit:** 6eb2065

## Claims vs Evidence

### Claim 1: Dual state sources (lines 140-144, 159)

**Line numbers WRONG.** The submission claims lines 140-144 and 159 — those are inside the `DETECTORS` dict (`flat_dirs` and `single_use` entries). The actual dual-state code is at:
- Line 397-404: `_RUNTIME` initialization with `judgment_detectors`
- Line 410: `JUDGMENT_DETECTORS: frozenset[str] = _RUNTIME.judgment_detectors`

The pattern itself is real — both `_RUNTIME.judgment_detectors` and the module-level `JUDGMENT_DETECTORS` exist. But the line references are fabricated.

### Claim 2: Implicit dependencies / stale binding

**TRUE.** `concerns.py:20` does `from desloppify.base.registry import JUDGMENT_DETECTORS`, creating a local binding that goes stale after `register_detector()` rebinds the name in registry's namespace. Used at concerns.py lines 436 and 485.

### Claim 3: Test isolation impossible

**OVERSTATED.** `reset_registered_detectors()` (line 432) exists specifically to reset global state between tests. The submission ignores this function entirely.

### Claim 4: Thread-unsafe

**IRRELEVANT.** desloppify is a single-user CLI tool. CPython's GIL provides safety for the simple attribute rebinding. Thread safety is not a meaningful concern here.

### Claim: "Line 159: JUDGMENT_DETECTORS: frozenset[str] = _RUNTIME.judgment_detectors"

**WRONG.** Line 159 is: `"inline or relocate with 'desloppify move'"` (inside the single_use detector entry). The actual JUDGMENT_DETECTORS assignment is at **line 410**.

### Claim: "Lines 170-171: global JUDGMENT_DETECTORS followed by mutation"

**WRONG.** Lines 170-171 are: `tool="move"` and `needs_judgment=True` (inside the coupling detector entry). The actual `global JUDGMENT_DETECTORS` is at **line 420** in `register_detector()`.

## Duplicate Analysis

**This is a duplicate of S028** (@dayi1000, submitted 2026-03-05T01:07:06Z, ~17 hours earlier).

S028 Issue 1 identifies the exact same problem:
- Same dual state (`_RUNTIME.judgment_detectors` vs module-level `JUDGMENT_DETECTORS`)
- Same stale binding mechanism (Python `from import` creates local copy)
- Same affected file (`concerns.py` lines 436, 485)
- Same root cause analysis (frozenset rebinding vs dict mutation)
- Correct fix proposed (attribute access or function)

S028 was verified as **YES_WITH_CAVEATS** (5/6/4/5).

## Verdict

| Question | Answer | Reasoning |
|----------|--------|-----------|
| **Is this poor engineering?** | YES | The dual-state pattern with stale binding risk is a real issue |
| **Is this at least somewhat significant?** | NO | Duplicate of S028 with wrong line numbers |

**Final verdict:** NO — Duplicate of S028 with fabricated line numbers (all three references point to wrong code). The core observation is valid but was already identified with greater precision by S028.

## Scores

| Criterion | Score |
|-----------|-------|
| Significance | 3/10 |
| Originality | 1/10 |
| Core Impact | 2/10 |
| Overall | 2/10 |
