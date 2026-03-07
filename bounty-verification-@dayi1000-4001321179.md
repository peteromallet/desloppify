**Issue:** https://github.com/peteromallet/desloppify/issues/204
**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4001321179
**Author:** @dayi1000

## Problem (in our own words)

Two claims: (1) `concerns.py` imports `JUDGMENT_DETECTORS` by value from `registry.py` at import time; when `register_detector()` later rebinds the module-level name to a new frozenset, the imported copy in `concerns.py` stays stale. (2) `do_run_batches` in `execution.py` takes too many parameters (claimed 23), making it a god function.

## Evidence

### Issue 1: Stale Import Binding

- `registry.py:404` — `JUDGMENT_DETECTORS: frozenset[str] = _RUNTIME.judgment_detectors` is a module-level frozenset.
- `registry.py:418-427` — `register_detector()` uses `global JUDGMENT_DETECTORS` to rebind the name, creating a new frozenset each time.
- `concerns.py:20` — `from desloppify.base.registry import JUDGMENT_DETECTORS` captures the frozenset object at import time.
- `concerns.py:436,485` — Uses the local `JUDGMENT_DETECTORS` binding, which is stale after any `register_detector()` call.
- `generic.py:146` — `register_detector()` is called during language plugin setup via `_register_generic_tool_specs()`.
- The contrast with `DETECTORS = _RUNTIME.detectors` (mutable dict, shared reference) is correctly identified — two inconsistent patterns side-by-side.

**Confirmation:** The stale binding pattern is real. `from module import name` copies the reference at import time; rebinding `name` in the source module does not propagate. Since `frozenset` is immutable, updates require rebinding, which breaks the imported copy.

**Practical impact is limited:** `register_detector()` is only called during language plugin setup (`generic.py:146`), which happens during initial scan setup. The concern generators in `concerns.py` run later during analysis. In practice, the registration completes before `JUDGMENT_DETECTORS` is read in concerns.py. However, if registration order ever changes (e.g., lazy plugin loading), this would silently produce wrong results with no error.

### Issue 2: do_run_batches God Function

- `execution.py:391` — `do_run_batches` has **22** parameters (4 positional + 18 keyword-only), not 23 as claimed.
- This is a **duplicate of S023** (@jasonsutter87, submitted 2026-03-05T00:43:52Z, 23 minutes before S028 at 01:07:06Z), which provides more thorough analysis (22 params, 355 lines, 11 responsibilities, call site analysis).

## Fix

Issue 1 fix: Use `registry.JUDGMENT_DETECTORS` (attribute access via module reference) instead of `from ... import JUDGMENT_DETECTORS`, or expose via a function like `get_judgment_detectors()`. This ensures the latest value is always read.

Issue 2: No additional fix beyond what S023 already describes — this is a duplicate.

## Verdict

| Question | Answer | Reasoning |
|----------|--------|-----------|
| **Is this poor engineering?** | YES | The stale frozenset import binding is a real correctness bug pattern with inconsistent usage vs. the mutable dict approach |
| **Is this at least somewhat significant?** | YES | Issue 1 is a genuine latent bug in core registry plumbing; Issue 2 is valid but duplicated by S023 |

**Final verdict:** YES_WITH_CAVEATS

- Issue 1 (stale import binding) is original and correctly analyzed, though practical impact is limited by current execution ordering.
- Issue 2 (do_run_batches) is a duplicate of S023 and the parameter count is off by one (22, not 23).

## Scores

| Criterion | Score |
|-----------|-------|
| Significance | 5/10 |
| Originality | 6/10 |
| Core Impact | 4/10 |
| Overall | 5/10 |

## Summary

The stale import binding finding (Issue 1) is the original and technically sound part of this submission — it correctly identifies an inconsistency between how `DETECTORS` (mutable dict, shared reference) and `JUDGMENT_DETECTORS` (immutable frozenset, copied on import) propagate updates. The practical risk is low today but represents a genuine latent bug. Issue 2 (do_run_batches god function) is a duplicate of S023 with a minor parameter miscount.

## Why Desloppify Missed This

- **What should catch:** A detector for stale import bindings of module-level globals that get reassigned (especially immutable types like frozenset/tuple).
- **Why not caught:** No detector analyzes import binding semantics vs. mutation patterns. The `global_mutable_config` detector focuses on mutable state, not stale immutable references.
- **What could catch:** A "stale-import-binding" detector that flags `from module import X` where X is later reassigned via `global X; X = ...` in the source module, especially for immutable types.

## Verdict Files

- [Verdict JSON](https://github.com/xliry/desloppify/blob/fix/bounty-4001321179-dayi1000/bounty-verdicts/%40dayi1000-4001321179.json)
- [Verdict Report](https://github.com/xliry/desloppify/blob/fix/bounty-4001321179-dayi1000/bounty-verification-%40dayi1000-4001321179.md)

Generated with [Lota](https://github.com/xliry/lota)
