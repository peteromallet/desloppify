# Bounty Verification: S118 @kmccleary3301

## Submission
- **ID:** S118
- **Author:** @kmccleary3301
- **Comment:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4003258017
- **Snapshot commit:** 6eb2065

## Claim Summary
`do_import_run()` is a semantic fork of the normal batch finalization path but omits `review_scope`, `reviewed_files`, and `assessment_coverage` metadata. This causes the auto-resolve logic to treat a partial import replay as a full sweep, silently closing unrelated holistic issues in dimensions not covered by the replay.

## Verification

### Claim 1: Normal path sets scope metadata, import path does not

**CONFIRMED.**

Normal path `_merge_and_write_results` (execution.py:253-340) sets:
- `merged["review_scope"]` with `full_sweep_included` (bool), `reviewed_files_count`, `successful_batch_count` (line 292)
- `merged["reviewed_files"]` (line 294)
- `merged["assessment_coverage"]` with `scored_dimensions`, `selected_dimensions`, `imported_dimensions`, `missing_dimensions` (line 327)

Import path `do_import_run` (orchestrator.py:320-423) sets only:
- `merged["provenance"]` (line 384)

No `review_scope`, `reviewed_files`, or `assessment_coverage` is set.

### Claim 2: Missing full_sweep_included defaults to None

**CONFIRMED.**

In `holistic.py:62-67`:
```python
review_scope = issues_data.get("review_scope", {})
if not isinstance(review_scope, dict):
    review_scope = {}
review_scope.setdefault("full_sweep_included", None)
scope_full_sweep = review_scope.get("full_sweep_included")
if not isinstance(scope_full_sweep, bool):
    scope_full_sweep = None
```

When `review_scope` is absent from the merged data, `scope_full_sweep` becomes `None`.

### Claim 3: None causes unscoped auto-resolve

**CONFIRMED.**

In `holistic_issue_flow.py:195-205`:
```python
scoped_reimport = full_sweep_included is False
# ...
if not scoped_reimport:
    return True  # resolve ALL stale holistic issues
```

When `full_sweep_included` is `None`, `scoped_reimport` is `False`, and `_should_resolve()` returns `True` for every stale holistic issue regardless of dimension. A replay importing only `test_strategy` will also auto-resolve issues in `dependency_health`, `error_handling`, etc.

### Claim 4: Runtime repro path

**CONFIRMED.** The described repro scenario is mechanically correct:
1. Seed open holistic issues in multiple dimensions
2. Replay via `--import-run` with payload covering only one dimension
3. All stale holistic issues across all dimensions are auto-resolved (not just the replayed dimension)

### Minor Inaccuracy
The submission states `_merge_and_write_results` is in `orchestrator.py` — it's actually in `execution.py`. Both functions are in the same `batch/` package, so the comparison is still valid.

## Duplicate Check
No prior submissions cover `do_import_run` scope metadata omission. This is an original finding.

## Verdict: YES

| Criterion | Score | Reasoning |
|-----------|-------|-----------|
| Significance | 7/10 | Real bug that silently destroys issue state during an official workflow |
| Originality | 8/10 | No prior submissions identify this code path divergence |
| Core Impact | 6/10 | Affects `--import-run` users; mitigated by being a recovery workflow (less frequent than normal path) |
| Overall | 7/10 | Clear, well-evidenced finding with correct repro and fix direction |

## Fix
Add the same `review_scope`, `reviewed_files`, and `assessment_coverage` metadata construction to `do_import_run` that `_merge_and_write_results` provides, or refactor to share the metadata-enrichment step.
