# Bounty Verification: S212 @BlueBirdBack — Circular Dependency with Divergent Merge Logic

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4009388140
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. Circular dependency between core.py and merge.py
**CONFIRMED.** `core.py:688` does `from .merge import merge_batch_results as _merge_batch_results` inside the `merge_batch_results` function body (deferred import to avoid cycle). `merge.py:17-27` imports types and private helpers (`_compute_merged_assessments`, `_issue_identity_key`, `assessment_weight`, `BatchIssuePayload`, `BatchResultPayload`, `BatchDimensionNotePayload`, etc.) back from `core.py` at module level.

### 2. core.py:681 exposes merge_batch_results via function-local import
**CONFIRMED.** `core.py:681` defines `merge_batch_results()` which at line 688 does `from .merge import merge_batch_results as _merge_batch_results` and delegates to it. This is exactly the abstraction inversion described.

### 3. Divergent `_should_merge_issues` implementations
**CONFIRMED.** Both files define `_should_merge_issues` with different behavior:

- **core.py:587** — Jaccard word overlap threshold of **0.3**. Related-file overlap is a standalone fallback. When no summary exists, defaults to allowing merge (`return True`).
- **merge.py:41** — Word overlap threshold of **0.45**. Uses a multi-signal approach: counts `summary_similarity_signal`, `file_overlap_signal`, and `identifier_signal`. Requires either (identifier match + one other signal) or (2+ corroborating signals). Much stricter.

### 4. Divergent `_merge_issue_payload` implementations
**CONFIRMED but functionally identical.** Both `core.py:576` and `merge.py:31` define `_merge_issue_payload` with the same logic: `merge_list_fields`, `pick_longer_text` for summary/suggestion, and `track_merged_from`. The duplication exists but doesn't produce different behavior.

### 5. Concrete behavioral divergence example
**CONFIRMED.** An issue pair with 35% summary word overlap and no file overlap:
- `core.py`: 0.35 >= 0.3 → returns `True` (merge)
- `merge.py`: 0.35 < 0.45 → `summary_similarity_signal = False`, no file/identifier signals → `corroborating_signals = 0` → returns `False` (no merge)

### 6. Active code path goes through merge.py
**CONFIRMED.** `core.py:merge_batch_results` delegates to `merge.py:merge_batch_results` via the deferred import. The `_should_merge_issues` in `core.py` is never called — it is dead code that appears functional.

### 7. Line number accuracy
**SLIGHTLY OFF.** Submission says `core.py:591` — actual is `core.py:587` (off by 4). Submission says `merge.py:47` — actual is `merge.py:41` (off by 6). All other line references (core.py:681, merge.py:17) are exact.

## Duplicate Check
- **S078** (@samquill) covers divergent `confidence_weights` between batch scoring and canonical definition — different files, different issue.
- No other submission covers the `_should_merge_issues` divergence between core.py and merge.py.

## Assessment
This is a high-quality submission that identifies a real, concrete engineering problem:

1. **Genuine circular dependency** with an abstraction inversion (merge module depends on core internals, core depends on merge for its public API).
2. **Genuinely divergent merge strategies** that produce different results on real inputs — not just style differences.
3. **Dead code masquerading as live code** — core.py's `_should_merge_issues` looks functional but is never executed, creating a debugging trap.
4. **Well-reasoned impact analysis** — correctly identifies that a maintainer could modify the wrong file and tests could pass against stale logic.

The only minor issue is slightly inaccurate line numbers (off by 4-6 lines), which doesn't undermine the substance.
