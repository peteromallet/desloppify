# Bounty Verification: S031 @xinlingfeiwu — Over-Injection Anti-Pattern in Review Pipeline

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4001550184
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `build_review_context_inner` receives regex constants as injected parameters (context_builder.py:13)
**CONFIRMED.** At `context_builder.py:13-32`, the function signature accepts `func_name_re`, `class_name_re`, `name_prefix_re`, and `error_patterns` as keyword parameters. The sole call site at `context.py:98-116` always passes:
- `func_name_re=FUNC_NAME_RE` (from `_context/patterns.py:7`)
- `class_name_re=CLASS_NAME_RE` (from `_context/patterns.py:8`)
- `name_prefix_re=NAME_PREFIX_RE` (from `_context/patterns.py:16`)
- `error_patterns=ERROR_PATTERNS` (from `_context/patterns.py:10-15`)

These are module-level compiled `re.Pattern` constants that never vary. The submission actually understates the issue — ALL 10+ keyword params (`read_file_text_fn`, `abs_path_fn`, `rel_fn`, `importer_count_fn`, `default_review_module_patterns_fn`, `gather_ai_debt_signals_fn`, `gather_auth_context_fn`, `classify_error_strategy_fn`) are also always the same module-level functions at the sole call site.

### 2. `prepare_holistic_review_payload` has 14 `_fn` params with one call site (prepare_holistic_flow.py:345)
**CONFIRMED.** The function at `prepare_holistic_flow.py:345` accepts 14 keyword-only function parameters plus `logger`:
`is_file_cache_enabled_fn`, `enable_file_cache_fn`, `disable_file_cache_fn`, `build_holistic_context_fn`, `build_review_context_fn`, `load_dimensions_for_lang_fn`, `resolve_dimensions_fn`, `get_lang_guidance_fn`, `build_investigation_batches_fn`, `batch_concerns_fn`, `filter_batches_to_dimensions_fn`, `append_full_sweep_batch_fn`, `serialize_context_fn`, `log_best_effort_failure_fn`.

The sole production call site is `prepare.py:231` (`prepare_holistic_review`), which always passes the same module-level imports.

### 3. Tests don't substitute via injection points
**CONFIRMED.** `test_holistic_review.py` tests `prepare_holistic_review` (the wrapper in `prepare.py`) using `monkeypatch.setattr` on module-level symbols (e.g., `desloppify.engine.concerns.generate_concerns`), not by passing alternate implementations through the `_fn` parameters. The injection points are unused for testing.

### 4. `_runner_process_types.py` shows a better established pattern
**CONFIRMED.** `_runner_process_types.py` defines `CodexBatchRunnerDeps` and `FollowupScanDeps` as frozen dataclasses that bundle dependencies. This is a cleaner, established pattern in the same codebase that the review pipeline doesn't follow.

## Duplicate Check
No other submissions found covering this specific over-injection pattern in the review pipeline.

## Assessment
The submission correctly identifies a real over-engineering pattern across three layers. The analysis is well-structured and the code references are accurate.

**Caveats:**
1. **DI for functions (not constants) can be legitimate.** While `func_name_re` et al. are clearly constants that should be imported directly, function params like `build_review_context_fn` and `serialize_context_fn` could legitimately vary in theory — it's the absence of any actual variation that makes them unnecessary.
2. **Not causing bugs.** This is a maintainability issue, not a correctness issue. The code works correctly; the injection just adds unnecessary signature complexity.
3. **Partial decomposition already happened.** `prepare_holistic_flow.py` itself contains internal helper functions (`_resolve_review_files`, `_build_review_contexts`, `_resolve_dimension_context`) that properly narrow the dependency surface. The top-level function is the bottleneck.
