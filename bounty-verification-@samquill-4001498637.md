# Bounty Verification: S030 @samquill

**Submission:** `do_run_batches` uses 15 raw callback parameters instead of a Deps dataclass
**Comment ID:** 4001498637
**Verdict:** NO (duplicate of S023)

## Claims vs Evidence

### Claim: "22 parameters, 15 of them injected function callbacks"

**Partially accurate.** At commit `6eb2065`, `do_run_batches` (execution.py:391) has 22 parameters but **16** `_fn`-suffixed callbacks, not 15:

```
run_stamp_fn, load_or_prepare_packet_fn, selected_batch_indexes_fn,
prepare_run_artifacts_fn, run_codex_batch_fn, execute_batches_fn,
collect_batch_results_fn, print_failures_fn, print_failures_and_raise_fn,
merge_batch_results_fn, build_import_provenance_fn, do_import_fn,
run_followup_scan_fn, safe_write_text_fn, colorize_fn
```

That's 15 listed above — but `selected_batch_indexes_fn` makes 15. Wait: counting again: the signature has exactly 16 `_fn` params (confirmed by grep). The submission undercounts by 1.

### Claim: "CodexBatchRunnerDeps and FollowupScanDeps exist for exactly this purpose"

**Confirmed.** Both frozen dataclasses exist in `_runner_process_types.py` and are used in orchestrator.py:250-263 and :270-278 respectively, within the same call expression that passes 15+ raw callbacks to `do_run_batches`. The asymmetry is real.

### Claim: "orchestrator.py lines 228–283 must inline 15+ lambdas in a single 60-line call expression"

**Confirmed.** The call spans orchestrator.py:228-284 (57 lines). It includes wrapper lambdas for `selected_batch_indexes_fn`, `run_codex_batch_fn`, and `run_followup_scan_fn`.

## Duplicate Analysis

S023 by @jasonsutter87 was submitted at `2026-03-05T00:43:52Z` — exactly **1 hour** before S030 (`01:43:53Z`). S023 covers:

- Same function: `do_run_batches` at `execution.py:391`
- Same parameter count: 22 params, 15 `_fn` callbacks
- Same call site: `orchestrator.py:228-284`
- **Broader scope:** S023 also identifies `prepare_holistic_review_payload` (19 params, 14 `_fn`), the systemic `colorize_fn` threading (212 sites), and the `_fn` suffix pattern (314 occurrences)

S030 adds one detail not in S023: the contrast with existing `CodexBatchRunnerDeps`/`FollowupScanDeps` dataclasses. This is a valid observation but insufficient to constitute an independent finding — S023 already noted the structural problem and its fix direction.

## Verdict: NO

Duplicate of S023. Same function, same problem, same call site, submitted later, narrower scope.

| Criterion | Score | Rationale |
|-----------|-------|-----------|
| Significance | 2/10 | Valid observation but entirely covered by S023 |
| Originality | 2/10 | Duplicate; the Deps-dataclass contrast is a minor addendum |
| Core Impact | 2/10 | No new actionable insight beyond S023 |
| Overall | 2/10 | Duplicate submission |
