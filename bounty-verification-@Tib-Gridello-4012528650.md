# Bounty Verification: S249 @Tib-Gridello

**Submission:** Anti-Gaming Check Active Only Between Scan and First Subsequent Operation
**Comment ID:** 4012528650
**Snapshot commit:** 6eb2065

## Summary

The anti-gaming integrity check protects 60% of `overall_score` (via `SUBJECTIVE_WEIGHT_FRACTION=0.60`). The submission claims this protection is erased after the first post-scan operation (resolve, filter, or import) because those operations call `_recompute_stats` without the `subjective_integrity_target`, overwriting `state["subjective_integrity"]` with `{status: "disabled", target_score: None}`.

## Verification

### Claim 1: `_update_objective_health` unconditionally sets `state["subjective_integrity"]` to baseline when target is None

**VERIFIED** — `state_integration.py:252-259`:
```python
integrity_target = _normalize_integrity_target(subjective_integrity_target)
integrity_meta = _subjective_integrity_baseline(integrity_target)
# ...
state["subjective_integrity"] = integrity_meta  # line 259
```
When `subjective_integrity_target` is `None`, `_normalize_integrity_target` returns `None`, and `_subjective_integrity_baseline(None)` returns `{"status": "disabled", "target_score": None}`.

### Claim 2: Three state-modifying operations trigger this erasure

**VERIFIED:**
1. `resolve_issues()` at `resolution.py:171`: `_recompute_stats(state, scan_path=state.get("scan_path"))` — no target
2. `remove_ignored_issues()` at `filtering.py:133`: `_recompute_stats(state, scan_path=state.get("scan_path"))` — no target
3. `import_holistic_issues()` via `holistic.py:129` → `merge_scan()` at `merge.py:195`: `MergeScanOptions` defaults `subjective_integrity_target` to `None` at `merge.py:120`

### Claim 3: Recovery mechanism defeated

**VERIFIED** — `persistence.py:147-158`: `_resolve_integrity_target` tries to recover `target_score` from `state["subjective_integrity"]`, but by the time `save_state` calls it, the earlier `_recompute_stats` (from resolution/filtering) has already overwritten `state["subjective_integrity"]["target_score"]` to `None`.

### Claim 4: Scan passes target correctly

**VERIFIED** — `scan/workflow.py:418,432,442`: `target_strict_score_from_config(runtime.config)` is passed to both `MergeScanOptions.subjective_integrity_target` and `save_state(..., subjective_integrity_target=target_score)`.

### Claim 5: Penalties applied on deepcopy, originals unchanged

**VERIFIED** — `state_integration.py:116`: `adjusted = deepcopy(subjective_assessments)`. The penalized copy is passed to `compute_score_bundle` for one computation. `state["subjective_assessments"]` is never modified — original gamed values survive intact.

### Claim 6: Config defaults

**VERIFIED** — `config.py:33`: `DEFAULT_TARGET_STRICT_SCORE = 95.0`, `config.py:442`: `target_strict_score_from_config`.

## Workflow trace

1. `desloppify scan` → sets `state["subjective_integrity"] = {status: "pass"/"penalized", target_score: 95.0}` (with penalties on discarded deepcopy)
2. `desloppify resolve` → `resolution.py:171` calls `_recompute_stats` without target → `state["subjective_integrity"] = {status: "disabled", target_score: None}`
3. `save_state_or_exit` → `_resolve_integrity_target(state, None)` reads `target_score: None` → returns `None` → anti-gaming permanently disabled

## Duplicate check

- S089: About attestation text validation (syntactic-only check) — different mechanism
- S147: About suppression integrity contradicting scoring — different
- S154: About tri-state `full_sweep_included` logic — different entry point/effect
- No prior submission identifies this specific `subjective_integrity_target` erasure mechanism

## Verdict

**YES** — All 6 claims verified with correct line references. Real bug: the anti-gaming check that protects 60% of the overall score is permanently erased after the first post-scan resolve/filter/import. The fix is straightforward: pass `target_strict_score_from_config` in the three non-scan code paths, matching what `scan/workflow.py` already does. Original finding with no duplicates.

## Scores

| Criterion | Score | Rationale |
|-----------|-------|-----------|
| Significance | 7 | Anti-gaming protection for 60% of overall_score effectively dead after first post-scan op |
| Originality | 7 | No prior submission covers this specific integrity target erasure mechanism |
| Core Impact | 6 | Real scoring integrity bug; straightforward fix (pass config target in 3 paths) |
| Overall | 7 | Well-documented, all references accurate, original finding with clear impact |
