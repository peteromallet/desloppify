# Bounty Verification: S055 @mpoffizial — object-typed callable dependencies

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4001742909
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `CodexBatchRunnerDeps` and `FollowupScanDeps` use `object` for callables
**CONFIRMED.** At `_runner_process_types.py:11-34`, seven fields use `object`:
- `CodexBatchRunnerDeps`: `subprocess_run: object`, `safe_write_text_fn: object`, `subprocess_popen: object | None`, `sleep_fn: object`
- `FollowupScanDeps`: `subprocess_run: object`, `colorize_fn: object`
- `_AttemptContext`: `safe_write_text_fn: object`

### 2. "Pattern repeats across 6+ runner files (~1,400 lines)"
**OVERSTATED.** The `object` type annotations are defined in exactly 1 file (`_runner_process_types.py`, 92 lines). There are 10 non-test runner files totaling ~2,171 lines, but the `object` typing is concentrated in the types file only.

### 3. "20+ call sites where these deps are invoked"
**SLIGHTLY OVERSTATED.** Actual count at snapshot:
- `_runner_process_attempts.py`: 11 call sites (`deps.subprocess_popen`, `deps.sleep_fn`, `deps.subprocess_run`, `deps.safe_write_text_fn`)
- `runner_process.py`: 6 call sites (`deps.safe_write_text_fn`, `deps.colorize_fn`, `deps.subprocess_run`)
- `test_runner_internals.py`: 3 call sites (test code)
- **Total: 17 production call sites**, not 20+

### 4. Static analysis is defeated
**CONFIRMED.** `object` type means mypy/pyright cannot verify argument types, return types, or arity at any of the 17 call sites. IDE autocompletion and signature hints are unavailable. A function with wrong signature would only fail at runtime.

## Duplicate Check
No prior submissions cover this specific pattern. S071 and S165 are broad architecture critiques that do not mention `object`-typed callables specifically.

## Assessment
The core observation is valid: using `object` for callable dependencies is genuinely poor typing practice that defeats the purpose of type annotations. The submission correctly identifies that this is "worse than having none at all" because it gives false confidence.

However, caveats apply:
1. **Scope overstated**: The pattern exists in 1 type definition file affecting 2 runner files, not "6+ runner files."
2. **Impact is contained**: This affects only the batch runner subsystem (~550 lines of consuming code), not the broader codebase.
3. **Trivial fix**: As the submission acknowledges, the fix is straightforward — `Callable` annotations or `Protocol` classes.
4. **Not a bug**: No runtime failures result from this pattern. It is a typing hygiene issue that reduces refactoring safety.
5. **Common in rapid Python development**: While not ideal, `object` as a quick stand-in for callable types is a known pattern in Python codebases under active development.
