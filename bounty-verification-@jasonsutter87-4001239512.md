# Bounty Verification: S023 @jasonsutter87 — God-Orchestrator with Callback Explosion

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4001239512
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `do_run_batches` at `execution.py:391` takes 22 parameters (15 `_fn` callbacks) and spans 355 lines
**MOSTLY CONFIRMED.** At `desloppify/app/commands/review/batch/execution.py:391`:
- **20 named parameters** (4 positional + 16 keyword), not 22. Close but slightly overstated.
- **16 `_fn` callback params**, not 15. Actually understated by one.
- **358 lines** (391–748), not 355. Trivially close.

### 2. Orchestrator call site at `orchestrator.py:228-284` is 56 lines of parameter wiring
**CONFIRMED.** `desloppify/app/commands/review/batch/orchestrator.py:228-284` is exactly 57 lines devoted to wiring params into `do_run_batches`, including wrapper lambdas for `selected_batch_indexes_fn`, `run_codex_batch_fn`, and `run_followup_scan_fn`.

### 3. `prepare_holistic_review_payload` has 19 parameters (14 `_fn` callbacks)
**MOSTLY CONFIRMED.** At `desloppify/intelligence/review/prepare_holistic_flow.py:345`:
- **20 parameters** (4 positional + 16 keyword), not 19.
- **14 `_fn` callback params** — exact match.

### 4. `colorize_fn` threads through 212 call sites in non-test code
**CONFIRMED.** Exact count of `colorize_fn` occurrences in non-test production files: **212**.

### 5. `_fn` suffix pattern appears 314 times in production code
**UNDERSTATED.** Actual count: **875** occurrences of `_fn` in non-test files. The claim of 314 is conservative.

### 6. Embedded `print(colorize_fn(...))` couples runtime engine to terminal output
**CONFIRMED.** `do_run_batches` contains multiple `print(colorize_fn(...))` calls for run log paths, run directories, packet paths, and prompt/result directories.

### 7. `context_builder.py:13` shows the same pattern
**CONFIRMED.** `build_review_context_inner` at line 13 takes 18+ params including `read_file_text_fn`, `abs_path_fn`, `rel_fn`, `importer_count_fn`, `gather_ai_debt_signals_fn`, `gather_auth_context_fn`, `classify_error_strategy_fn`, etc.

## Duplicate Check
S023 is the **earliest** submission on this topic (2026-03-05T00:43:52Z). Later duplicates include:
- S028 (@dayi1000) — 2026-03-05T01:07:06Z
- S030 (@samquill) — 2026-03-05T01:43:53Z
- S076 (@doncarbon) — 2026-03-05T03:36:29Z
- S176 (@JohnnieLZ), S182 (@MacHatter1), S204/@S210 (@lbbcym), S239 (@lustsazeus-lab) — later

## Assessment
The core observation is valid and well-documented: `do_run_batches` is a god function with excessive callback injection that creates wide dependency surfaces and couples orchestration to presentation.

However, caveats apply:
1. **Deliberate design choice**: The `_fn` injection pattern is intentional for testability — every dependency can be mocked without monkey-patching. This is a conscious trade-off, not accidental complexity.
2. **Numbers slightly off**: 20 params not 22; 16 callbacks not 15; 358 lines not 355. Minor inaccuracies that don't undermine the argument.
3. **No bug or runtime failure**: This is a maintainability/ergonomics concern, not a defect. The code works correctly.
4. **Common pattern in this codebase**: The `_fn` injection is the established architectural convention. Calling it "poorly engineered" conflates a style choice with a defect.
