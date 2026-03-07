# Bounty Verification: S002 @yuliuyi717-ux — State-Model Coupling

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4000447540
**Snapshot:** `6eb2065fd4b991b88988a0905f6da29ff4216bd8`
**Verdict:** YES_WITH_CAVEATS (Overall: 3/10)

## Claim

The same mutable state document (`StateModel`) is used as evidence truth, operator-decision log, and score cache. This creates non-commutative behavior, provenance ambiguity, and scaling risk.

## Code Trace

### 1. schema.py — StateModel co-locates raw issues with derived scores

`desloppify/engine/_state/schema.py:322-339`

`StateModel` is a single `TypedDict` that holds:
- `issues` — raw issue records from detectors (evidence truth)
- `stats`, `strict_score`, `verified_strict_score`, `objective_score`, `overall_score` — derived scoring fields (score cache)
- `subjective_assessments` — operator/reviewer dimension scores (decision log)
- `dimension_scores` — per-dimension score breakdowns (derived)
- `resolution_attestation` fields on individual `Issue` records — manual operator decisions

**Verified:** Yes, the co-location is real. All these concerns live in one dict.

### 2. merge.py — merge_scan mutates issues and recomputes scores

`desloppify/engine/_state/merge.py:123-199`

The `merge_scan` function:
1. Calls `upsert_issues()` to add/update/reopen issue records in `state["issues"]`
2. Calls `auto_resolve_disappeared()` to mark vanished issues as auto-resolved
3. Calls `_mark_stale_on_mechanical_change()` to flag subjective assessments
4. Calls `_recompute_stats(state)` to recalculate all derived scores from the mutated issues

**Verified:** Yes, issue lifecycle mutations and score recomputation happen in the same flow on the same object.

### 3. resolution.py — resolve_issues writes decisions and recomputes scores

`desloppify/engine/_state/resolution.py:99-173`

The `resolve_issues` function:
1. Iterates matching issues and mutates their `status`, `note`, `resolved_at`, `resolution_attestation`
2. Calls `_mark_stale_assessments_on_review_resolve()` to flag affected subjective dimensions
3. Calls `_recompute_stats(state)` to recalculate derived scores

**Verified:** Yes, operator decisions and score recomputation share the same mutable state.

## Assessment

The observation is **technically accurate** but the significance is **overstated**.

**What is real:**
- `StateModel` does serve triple duty as evidence store, decision log, and score cache
- Both `merge_scan` and `resolve_issues` mutate issues in-place then recompute derived scores
- There is no separation between "events" and "projections"

**What is overstated:**
- **Non-commutative behavior**: The tool runs sequentially as a CLI — scan/resolve ordering is deterministic in practice. There is no concurrent access.
- **Provenance ambiguity**: The state model already includes `resolution_attestation`, `attestation_log`, `scan_history`, and `assessment_import_audit` — these provide reasonable provenance tracking.
- **Scaling risk**: This is a single-user CLI tool. Event sourcing with projections would be significant over-engineering.
- The proposed architectural fix (immutable event log with deterministic projections) is a distributed-systems pattern inappropriate for a local CLI tool.

## Scores

| Criterion | Score | Reasoning |
|-----------|-------|-----------|
| Significance | 4/10 | Real coupling but low practical impact for a CLI tool |
| Originality | 3/10 | Standard observation about mutable state; no novel insight |
| Core Impact | 3/10 | Does not cause bugs or correctness issues in current usage |
| Overall | 3/10 | Valid observation, overstated significance |
