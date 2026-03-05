# S326 Verification: @kmccleary3301 — do_import_run() omits review_scope/reviewed_files/assessment_coverage

## Status: VERIFIED

## Claims

1. **`do_import_run()` omits `review_scope`, `reviewed_files`, and `assessment_coverage` metadata** from
   the merged JSON it writes before importing.
2. **Downstream impact:** missing `full_sweep_included` causes unscoped auto-resolution of stale holistic
   issues — all open holistic issues across ALL dimensions get resolved, not just those in the imported
   dimensions.

## Verification

### Claim 1: Missing metadata fields — CONFIRMED

The normal batch path in `_merge_and_write_results()` (`execution.py:253-337`) enriches the merged
result with three metadata fields before writing:

- `merged["review_scope"]` (line 292) — includes `full_sweep_included`, file counts, batch counts
- `merged["reviewed_files"]` (line 294) — list of files covered by successful batches
- `merged["assessment_coverage"]` (line 327-332) — scored/selected/imported/missing dimensions

The `do_import_run()` function (`orchestrator.py:320-423`) reconstructs and merges batch results
but only sets `merged["provenance"]` (line 384). It never sets `review_scope`, `reviewed_files`,
or `assessment_coverage`. The merged JSON written at line 393 is therefore missing all three fields.

### Claim 2: Unscoped auto-resolution — CONFIRMED

The import chain flows as follows:

1. `do_import_run()` calls `_do_import()` (orchestrator.py:397) which reads the merged JSON file.
2. `import_holistic_issues()` calls `holistic.py:import_holistic_review_issues()`.
3. At `holistic.py:62-68`, the code reads `review_scope` from the imported data:
   ```python
   review_scope = issues_data.get("review_scope", {})
   # ...
   review_scope.setdefault("full_sweep_included", None)
   scope_full_sweep = review_scope.get("full_sweep_included")
   if not isinstance(scope_full_sweep, bool):
       scope_full_sweep = None
   ```
   Since `review_scope` is missing from the import-run merged JSON, `full_sweep_included` defaults to `None`.

4. At `holistic_issue_flow.py:195-206`, the auto-resolution logic uses:
   ```python
   scoped_reimport = full_sweep_included is False
   ```
   When `full_sweep_included` is `None` (not `False`), `scoped_reimport` is `False`.

5. In `_should_resolve()` (line 205-206):
   ```python
   if not scoped_reimport:
       return True
   ```
   This returns `True` for ALL holistic issues regardless of dimension, causing unscoped resolution.

**Result:** A partial import-run replay (e.g., only 3 of 8 dimensions) will auto-resolve ALL open
holistic issues across all dimensions, not just the 3 that were actually re-imported. This silently
drops legitimate issues from dimensions that weren't part of the replay.

## Scoring

| Criterion | Score | Rationale |
|-----------|-------|-----------|
| **Significance** | 6 | Real data-loss bug: partial import-run replays silently resolve unrelated issues |
| **Originality** | 6 | Deep trace through 4-file import chain; non-obvious metadata omission |
| **Core Impact** | 4 | Affects issue lifecycle and scoring via silent resolution of valid findings |
| **Overall** | 5 | Verified bug with real downstream impact; import-run is a recovery path so usage frequency is lower |

## Files Referenced

- `desloppify/app/commands/review/batch/orchestrator.py:320-423` — `do_import_run()` missing metadata
- `desloppify/app/commands/review/batch/execution.py:253-337` — `_merge_and_write_results()` normal path with all metadata
- `desloppify/intelligence/review/importing/holistic.py:62-68` — `full_sweep_included` defaults to None
- `desloppify/intelligence/review/importing/holistic_issue_flow.py:180-217` — `auto_resolve_stale_holistic()` unscoped when None
