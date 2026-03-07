# Bounty Verification: S187 @ufct

**Issue:** https://github.com/peteromallet/desloppify/issues/204
**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4007430981
**Author:** @ufct

## Problem (in our own words)

`_state/filtering.py` uses a deferred (in-function) import of `recompute_stats` from `_scoring/state_integration.py` inside `remove_ignored_issues()`. This hides a circular dependency: the lower layer (`_state`) imports from the higher layer (`_scoring`), while `_scoring/state_integration.py` already top-level imports `path_scoped_issues` from `_state/filtering.py`. The deferred import prevents an `ImportError` at load time but masks the architectural violation from static analysis tools.

## Evidence

- `desloppify/engine/_state/filtering.py:129-131` (at commit 6eb2065): deferred import of `recompute_stats` from `_scoring.state_integration` inside `remove_ignored_issues()`
- `desloppify/engine/_scoring/state_integration.py:23-24` (at commit 6eb2065): top-level imports of `path_scoped_issues` from `_state.filtering` and `StateModel` from `_state.schema`
- This confirms a real circular dependency: `_state.filtering` ↔ `_scoring.state_integration`

## Fix

Pass `recompute_stats` as a callable parameter to `remove_ignored_issues()`, or move `remove_ignored_issues()` to a coordinator module above both `_state` and `_scoring`. Either approach eliminates the circular import.

## Verdict

| Question | Answer | Reasoning |
|----------|--------|-----------|
| **Is this poor engineering?** | YES | A lower-layer module importing upward into a higher layer violates the declared dependency hierarchy |
| **Is this at least somewhat significant?** | YES | The coupling prevents independent initialization/testing of `_state` and `_scoring`, though the practical impact is limited to one function |

**Final verdict:** YES_WITH_CAVEATS

## Scores

| Criterion | Score |
|-----------|-------|
| Significance | 4/10 |
| Originality | 5/10 |
| Core Impact | 4/10 |
| Overall | 4/10 |

## Summary

The submission correctly identifies a real circular dependency hidden by a deferred import. `_state/filtering.py` imports from `_scoring/state_integration.py` inside `remove_ignored_issues()`, while `state_integration.py` top-level imports from `_state/filtering.py`. This is a genuine layer violation. However, deferred imports to break circular dependencies are an extremely common and pragmatic Python pattern, and the coupling is limited to a single function. The impact is real but moderate — the fix is straightforward (dependency injection or relocation), and the pattern does not cause runtime failures.

## Why Desloppify Missed This

- **What should catch:** A layer-violation or circular-dependency detector that traces import graphs including deferred (in-function) imports
- **Why not caught:** Desloppify's detectors analyze code smells within files, not cross-module import dependency graphs
- **What could catch:** A `pydeps`-style import graph analysis that includes deferred imports, or a custom detector that flags in-function imports of sibling/parent packages

## Verdict Files

- [Verdict JSON](https://github.com/xliry/desloppify/blob/fix/bounty-4007430981-ufct/bounty-verdicts/%40ufct-4007430981.json)
- [Verdict Report](https://github.com/xliry/desloppify/blob/fix/bounty-4007430981-ufct/bounty-verification-%40ufct-4007430981.md)

Generated with [Lota](https://github.com/xliry/lota)
