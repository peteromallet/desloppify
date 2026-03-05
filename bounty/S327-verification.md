# S327 Verification: Duplicate action-priority tables with contradictory ordering

**Author:** @shanpenghui
**Status:** VERIFIED
**Scores:** Sig=4 | Orig=4 | Core=1 | Overall=3

## Claim

Duplicate action-priority tables exist with contradictory ordering between
`helpers.py` and `registry.py`.

## Verification

**Confirmed.** Three action-priority dictionaries exist with contradictory ordering:

| File | Variable | auto_fix | refactor | manual_fix | reorganize |
|------|----------|----------|----------|------------|------------|
| `engine/_work_queue/helpers.py:15` | `ACTION_TYPE_PRIORITY` | 0 | **1** | **2** | **3** |
| `base/registry.py:455` | `_ACTION_PRIORITY` | 0 | **2** | **3** | **1** |
| `core/registry.py:360` | `_ACTION_PRIORITY` | 0 | **2** | **3** | **1** |

The contradiction: `helpers.py` ranks refactor(1) above reorganize(3), while both
registry files rank reorganize(1) above refactor(2).

### Usage contexts

- `helpers.py` `ACTION_TYPE_PRIORITY` is used in `ranking.py:209` for sorting work
  queue clusters by action type
- `base/registry.py` `_ACTION_PRIORITY` is used in `dimension_action_type()` for
  picking the best action label for a scoring dimension
- `core/registry.py` `_ACTION_PRIORITY` is used in its own `dimension_action_type()`

### Additional finding: stale duplicate registry

`core/registry.py` is a stale diverged copy of `base/registry.py`:
- Missing fields: `tier`, `standalone_threshold`, `marks_dims_stale`
- Different `_ACTION_LABELS`: `"auto_fix": "fix"` vs `"auto_fix": "autofix"`
- Missing `_RegistryRuntime` class and `reset_registered_detectors()`
- Imported by only 2 files (`core/issues_render.py`, `app/commands/status_parts/render.py`)

## Impact Assessment

**UI/ordering only.** The contradictory priorities affect:
1. Work queue cluster sort order (which action types appear first)
2. Dimension action label selection (which action type "wins" for a dimension)

No impact on scoring calculations, data integrity, or gaming resistance.
The stale `core/registry.py` could cause display inconsistencies between
code paths that import from `base/` vs `core/`.
