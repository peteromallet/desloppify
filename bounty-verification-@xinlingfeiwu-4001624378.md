# Bounty Verification: S034 @xinlingfeiwu — app/ Bypasses Engine Facades

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4001624378
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. 57 private imports from app/ into engine._* modules
**CONFIRMED.** Exact grep across all 176 app/ files at the snapshot commit yields exactly 57 `from desloppify.engine._` import lines.

### 2. Per-package breakdown
**CONFIRMED.** Exact matches:
- `engine._work_queue`: 24 imports
- `engine._scoring`: 15 imports
- `engine._state`: 11 imports
- `engine._plan`: 7 imports

### 3. No public facades for _work_queue, _scoring, _state
**CONFIRMED.** `engine/plan.py` is the only facade module. No `engine/work_queue.py`, `engine/scoring.py`, or `engine/state.py` exist at the snapshot.

### 4. Specific code example from app/commands/next/cmd.py
**CONFIRMED.** The file contains exactly these private imports:
- `from desloppify.engine._scoring.detection import merge_potentials`
- `from desloppify.engine._work_queue.context import queue_context`
- `from desloppify.engine._work_queue.core import (...)`
- `from desloppify.engine._work_queue.plan_order import collapse_clusters`

### 5. "The same file imports engine.plan 42 times"
**INACCURATE.** The total public `engine.plan` imports across all of app/ is 33, not 42. The sentence also conflates per-file and codebase-level counts — no single file has 42 imports.

## Duplicate Check
- S235 (@demithras) covers similar ground with a broader scope (includes `intelligence/` layer, counts 87 imports across 55 files). However, S034 was submitted first (March 5 vs March 6) and has priority.
- No prior verified submissions cover this specific finding.

## Assessment
The core observation is valid and precisely quantified: `app/` bypasses private engine module boundaries 57 times, with exact per-package counts matching. The submission correctly identifies that only `engine/plan.py` exists as a facade while three other private packages have none.

Caveats:
1. **Minor count error**: Claims 42 legitimate facade imports; actual is 33.
2. **Common Python pattern**: Underscore-prefix conventions are advisory in Python. Many projects import from `_` packages when no facade exists — this is the expected behavior when facades haven't been created yet.
3. **Internal tool**: Desloppify is not a library with external consumers. The encapsulation boundary matters for maintainability but not for API stability.
4. **Not a bug**: No runtime failure results from this pattern. It's an architectural observation about incomplete encapsulation.
