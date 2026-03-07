# Bounty Verification: S076 @doncarbon — Callback-Parameter Explosion in Review Pipeline

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4001894964
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `do_run_batches()` takes 23 parameters with 15 injected function callbacks (execution.py:391)
**MOSTLY CONFIRMED (22 params, not 23).** At `execution.py:391`, the function has 4 positional + 18 keyword-only = **22 total parameters**. The 15 `_fn` callback count is correct: `run_stamp_fn`, `load_or_prepare_packet_fn`, `selected_batch_indexes_fn`, `prepare_run_artifacts_fn`, `run_codex_batch_fn`, `execute_batches_fn`, `collect_batch_results_fn`, `print_failures_fn`, `print_failures_and_raise_fn`, `merge_batch_results_fn`, `build_import_provenance_fn`, `do_import_fn`, `run_followup_scan_fn`, `safe_write_text_fn`, `colorize_fn`.

### 2. `prepare_holistic_review_payload()` takes 14 callback params (prepare_holistic_flow.py:345)
**CONFIRMED.** Exactly 14 `_fn` keyword-only parameters plus `logger` (19 total params: 4 positional + 15 keyword-only).

### 3. `build_review_context_inner()` takes 8 callback params (context_builder.py)
**CONFIRMED.** 8 `_fn` parameters: `read_file_text_fn`, `abs_path_fn`, `rel_fn`, `importer_count_fn`, `default_review_module_patterns_fn`, `gather_ai_debt_signals_fn`, `gather_auth_context_fn`, `classify_error_strategy_fn`. Plus 4 non-fn keyword params (regex patterns and `error_patterns`), for 16 total params.

### 4. Orchestrator wiring at lines 228-270 (orchestrator.py)
**CONFIRMED.** Lines 228–284 in `orchestrator.py` are devoted to wiring parameters into `do_run_batches`, including wrapper lambdas for `selected_batch_indexes_fn`, `run_codex_batch_fn`, and `run_followup_scan_fn`.

### 5. 18 functions across the codebase accept 3+ `_fn` callback parameters
**PLAUSIBLE.** At least 30 files contain 3+ `_fn` parameter references. The exact function count likely exceeds 18.

### 6. `_merge_and_write_results` at 15 params
**CONFIRMED.** The function at `execution.py` accepts 15 keyword-only parameters.

## Duplicate Check

**S076 is a DUPLICATE of S023** (@jasonsutter87, submitted 2026-03-05T00:43:52Z).

S023 (verified as YES_WITH_CAVEATS) covers the **exact same ground**:
- `do_run_batches` god function with callback explosion
- `prepare_holistic_review_payload` with 14 `_fn` params
- `build_review_context_inner` with the same pattern
- Systemic `_fn` suffix pattern across the codebase
- Orchestrator wiring complexity

S023 was submitted **~3 hours before** S076 (2026-03-05T03:36:29Z). The S023 verdict explicitly lists S076 as a known later duplicate.

Additionally, **S031** (@xinlingfeiwu) also covers the over-injection anti-pattern for `build_review_context_inner` and `prepare_holistic_review_payload`.

## Assessment

The technical analysis in S076 is accurate and well-structured. The callback-parameter explosion pattern is real. However, S023 already established priority on this finding with the same functions, the same analysis, and overlapping code references. S076 adds no new insight beyond what S023 already covers.

**Verdict: NO** — Duplicate of S023.
