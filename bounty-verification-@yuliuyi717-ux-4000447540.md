# Bounty Verification: S002 @yuliuyi717-ux

**Submission:** [#204 comment](https://github.com/peteromallet/desloppify/issues/204#issuecomment-4000447540)
**Commit:** `6eb2065`
**Claim:** State-model coupling — the same mutable state document serves as evidence truth, operator-decision log, and score cache.

## Analysis

### What the submission claims

1. `StateModel` co-locates raw issue records with derived scoring/summary fields (`issues`, `stats`, `strict_score`, `verified_strict_score`, `subjective_assessments`).
2. `merge_scan()` mutates issue lifecycle and recomputes scores in the same flow.
3. `resolve_issues()` writes manual decisions into the same records, then recomputes stats/scores.
4. This causes non-commutative behavior, provenance ambiguity, and scaling risk.

### What the code actually shows

The observations about code structure are **factually correct**:

- `schema.py:322-339` — `empty_state()` returns a single dict with `issues`, `stats`, `strict_score`, `verified_strict_score`, `subjective_assessments` all co-located.
- `merge.py:123-199` — `merge_scan()` upserts issues and calls `_recompute_stats()` in one flow.
- `resolution.py:99-173` — `resolve_issues()` writes status/note/attestation into issue records and calls `_recompute_stats()`.

However, the submission **overlooks existing provenance mechanisms**:

- `attestation_log` (schema.py:290) — records every resolve/suppress action with timestamps and attestation text.
- `assessment_import_audit` (schema.py:289) — tracks every subjective assessment import with mode, trust status, and provenance.
- `scan_history` (schema.py:278) — records per-scan snapshots of scores, issue counts, and diffs.
- `resolution_attestation` on each issue — captures the kind (manual/auto), text, and verification status.

### Why this is not poor engineering

1. **Appropriate for the domain.** Desloppify is a single-user CLI tool that runs scans sequentially. Mutable state in a single JSON document is the standard pattern for this class of tool. Event sourcing would be over-engineering.

2. **"Non-commutative behavior" is misleading.** Operations (scan, resolve, import) are inherently ordered — a resolve after scan is semantically different from a resolve before scan. The order mattering is correct behavior, not a bug.

3. **Provenance is already tracked.** The codebase maintains attestation logs, audit trails, and scan history snapshots. Score deltas can be attributed through `scan_history` entries which record scores at each scan boundary.

4. **"Scaling risk" doesn't apply.** The tool is not a concurrent service. It runs as a CLI in a single process. Concurrency and determinism concerns from event sourcing literature don't transfer.

5. **The DESLOPPIFY_INTERNALS.md itself documents this as a known design decision** (line 89): "State is mutable — scan results, scores, and resolutions all live in one document."

## Verdict

| Question | Answer | Reasoning |
|----------|--------|-----------|
| **Is this poor engineering?** | NO | Mutable single-document state is appropriate for a sequential CLI tool; provenance tracking already exists |
| **Is this at least somewhat significant?** | NO | The claimed risks (non-commutativity, concurrency) don't apply to this tool's usage model |

**Final verdict:** NO

## Scores

| Criterion | Score |
|-----------|-------|
| Significance | 3/10 |
| Originality | 4/10 |
| Core Impact | 2/10 |
| Overall | 3/10 |

## Summary

The submission correctly identifies that StateModel co-locates issues, scores, and operator decisions in one mutable document. However, this is a deliberate and appropriate design choice for a single-user CLI tool. The codebase already includes provenance tracking (attestation_log, assessment_import_audit, scan_history). The submission advocates for event sourcing, which would be over-engineering for this domain. The claimed risks around non-commutativity and concurrency do not apply.

## Why Desloppify Missed This

- **What should catch:** `cross_module_architecture` or `abstraction_fitness` subjective dimensions
- **Why not caught:** This is an architectural opinion about event sourcing vs. mutable state, not a concrete code quality issue that detectors can flag
- **What could catch:** Nothing — this is a design preference, not a defect
