# Bounty Verification: S235 @demithras

**Submission:** Systematic violation of private module boundaries -- 87 imports across 55 files bypass engine encapsulation

## Claims vs Evidence

### Claim 1: "87 import statements across 55 files in app/ and intelligence/ import directly from engine._*"
**VERIFIED.** Exact count confirmed at commit 6eb2065:
- `app/`: 57 imports
- `intelligence/`: 30 imports
- Total: 87 imports across 55 unique files

Breakdown by private subpackage:
- `engine._state`: 32 imports
- `engine._work_queue`: 24 imports
- `engine._scoring`: 24 imports
- `engine._plan`: 7 imports

### Claim 2: "A state.py facade at the package root re-exports selected symbols from engine._state.*"
**FALSE.** No `state.py` facade exists in `engine/` at the snapshot commit. Only `plan.py` is a facade (241 lines, re-exporting 77 symbols from `_plan`). The submission's analysis assumes a facade that doesn't exist.

### Claim 3: "63 bypass the facade entirely, importing symbols that state.py doesn't even re-export"
**MISLEADING.** Since there is no `state.py` facade, all 80 non-_plan imports bypass by necessity (nothing to use instead). Of the 7 `_plan` imports, 2 (`annotation_counts`, `USER_SKIP_KINDS`) are not re-exported by `plan.py`, while 3 (`detect_recurring_patterns`, `review_issue_snapshot_hash`) are available through `plan.py` but imported directly anyway.

### Claim 4: "The most imported private symbol is engine._state.schema.StateModel (24 direct imports)"
**MINOR INACCURACY.** Actual count is 27 direct imports, not 24.

### Claim 5: Specific examples
All 4 specific import examples verified as accurate:
- `app/commands/scan/workflow.py` -> `engine._work_queue.issues` ✓
- `app/commands/next/cmd.py` -> multiple `engine._*` modules ✓
- `app/commands/plan/cmd.py` -> `engine._plan.annotations`, `engine._plan.skip_policy` ✓
- `intelligence/review/importing/per_file.py` -> `engine._state.*` ✓

## Duplicate Analysis

**This is a duplicate of S034** (@xinlingfeiwu), which was verified as YES_WITH_CAVEATS (5/6/4/5).

S034 title: "app/ bypasses engine facades -- 57 private imports"
S034 verified counts: 57 private imports from app/ into engine._* (_work_queue:24, _scoring:15, _state:11, _plan:7)

S235 extends S034 by:
- Adding `intelligence/` layer (30 more imports)
- Higher total count (87 vs 57)
- But same core observation, same architectural concern

S034 correctly identified that only `plan.py` facade exists; S235 incorrectly claims a `state.py` facade exists.

## Verdict

**NO** -- Duplicate of S034. The core finding (private module boundary violations in engine/) is identical. S235 broadens scope to include intelligence/ imports but does not identify a novel architectural concern. S034 was submitted earlier and provided more accurate facade analysis.
