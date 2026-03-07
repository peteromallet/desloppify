# Bounty Verification: S072 @lee101 — Multi-Issue Submission

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4001870059
**Snapshot commit:** 6eb2065
**Note:** Author describes this as "work in progress from codex-infinity.com agent."

## Claims Verified

### 1. Fail-open persistence resets core data to empty state/plan
**CONFIRMED with caveats.** `engine/_state/persistence.py:126-138` does fall back to `empty_state()` on normalization failure, and `engine/_plan/persistence.py:68-73` falls back to `empty_plan()` on validation failure. However, the submission omits significant mitigations already present:
- State persistence tries a `.json.bak` backup before falling back (lines 66-97)
- Plan persistence also tries backup recovery (lines 40-49)
- Both emit stderr warnings and logger messages
- State persistence renames corrupted files to `.json.corrupted`

The "silent hard resets" framing is misleading — these are logged and warned. The real concern is that a single malformed field triggers full reset rather than partial salvage, which is valid but overstated.

### 2. Split-brain review batch lifecycle: duplicate state machines
**CONFIRMED.** `_build_progress_reporter` closure in `execution.py:46-120` and `BatchProgressTracker.report` in `batches_runtime.py:73-117` implement nearly identical progress reporting logic (queued/start/done events, status tracking, run log writing). The closure-based version is used by the active `do_run_batches` flow; `BatchProgressTracker` is a class-based alternative. Both exist and are maintained.

The duplication is real. Whether `BatchProgressTracker` is "abandoned" or an intentional refactoring-in-progress is unclear, but maintaining two implementations of the same contract is a valid concern.

### 3. Public/private boundary violated by command layer importing `_plan` internals
**CONFIRMED.** Despite `_plan/__init__.py` stating external code should use the `engine.plan` facade:
- `cmd.py:35` imports `annotation_counts` from `engine._plan.annotations`
- `cmd.py:36` imports `USER_SKIP_KINDS` from `engine._plan.skip_policy`
- `override_handlers.py:27-31` imports `SKIP_KIND_LABELS`, `skip_kind_from_flags`, etc. from `engine._plan.skip_policy`
- `stage_persistence.py:5` imports `review_issue_snapshot_hash` from `engine._plan.stale_dimensions`

These are real boundary violations. Some imports (like skip policy constants) might reasonably be exposed through the facade but aren't.

### 4. Triage guardrail fails open on broad load errors
**CONFIRMED.** `guardrails.py:33-36` catches `PLAN_LOAD_EXCEPTIONS` and returns `TriageGuardrailResult()` (which defaults to `is_stale=False`). `exception_sets.py:33` defines `PLAN_LOAD_EXCEPTIONS` as `(ImportError, AttributeError, OSError, ValueError, TypeError, KeyError)` — a very broad tuple. When plan loading fails for any reason, the guardrail reports "not stale," allowing operations to proceed without triage.

### 5. `make_lang_run` can alias mutable runtime state across scans
**CONFIRMED.** `runtime.py:297-298`: if `lang` is already a `LangRun`, the function returns the same instance without creating a fresh one. Downstream code mutates `lang.dep_graph` (e.g., `phases.py:628`, `phases_runtime.py:145`) and `lang.complexity_map` (`shared_phases.py:502`). If the same `LangRun` is reused across scans, state from one scan leaks into another.

### 6. Framework phase pipeline is forked and drifting
**PARTIALLY CONFIRMED.** The shared `run_structural_phase` in `shared_phases.py:488` calls `detect_complexity(..., min_loc=min_loc)` with a configurable parameter (default 40). Python's `run_phase_structural` in `phases_runtime.py:61` calls `detect_complexity(...)` without `min_loc`. This is a real API signature drift, though the behavioral impact depends on whether `detect_complexity` has a compatible default internally.

### 7. Corrupt config falls back to `{}` and may be persisted
**CONFIRMED.** `config.py:140-141`: `_load_config_payload` catches parse errors and returns `{}`. `load_config` at line 188-190 then fills defaults and, if `changed and p.exists()`, calls `save_config`. If the file existed but was corrupted, this overwrites it with defaults. The original corrupt content is lost without backup.

### 8. TypeScript detector phase re-scans the same corpus repeatedly
**CONFIRMED.** `phases.py:685-747`: `phase_smells` calls five separate detectors (`detect_smells`, `detect_state_sync`, `detect_context_nesting`, `detect_hook_return_bloat`, `detect_boolean_state_explosion`), each independently walking files. No shared AST cache or parsed representation is used. This is a valid performance concern for large codebases.

## Duplicate Check

- **Issue 1 (fail-open persistence):** S006 (@agustif) covers plan persistence's destructive migration strategy — related but not identical. S006 focuses on migration, S072 focuses on empty-state fallback. Partial overlap.
- **Issue 3 (_plan boundary):** Not previously reported as a standalone issue.
- **Issue 4 (guardrail fail-open):** Not previously reported.
- **Issue 5 (make_lang_run):** Not previously reported.
- **Issue 7 (config clobber):** S003 (@juzigu40-ui) covers config bootstrap non-transactional behavior — overlapping concern about config load/save side effects.
- **Issues 2, 6, 8:** Not previously reported as standalone issues.

## Assessment

This is a broad, shallow submission covering 8 issues. All claims are structurally confirmed against the codebase, though several are overstated (especially #1, where existing mitigations are ignored). The submission reads as automated output — it covers many files but rarely demonstrates deep understanding of the design trade-offs or why specific patterns were chosen.

The strongest individual findings are #2 (split-brain batch reporters), #4 (guardrail fail-open), and #5 (make_lang_run aliasing). The weakest are #1 (ignores existing mitigations) and #8 (performance concern without evidence of actual impact).

Several issues partially overlap with earlier submissions (S003, S006). The breadth-over-depth approach means no single issue reaches the insight level of focused submissions.

## Verdict

| Question | Answer | Reasoning |
|----------|--------|-----------|
| **Is this poor engineering?** | YES | Multiple confirmed patterns: duplicate state machines, boundary violations, fail-open guardrails, mutable aliasing |
| **Is this at least somewhat significant?** | YES | Split-brain batch code and make_lang_run aliasing could cause real bugs; guardrail fail-open defeats safety intent |

**Final verdict:** YES_WITH_CAVEATS

## Scores

| Criterion | Score |
|-----------|-------|
| Significance | 5/10 |
| Originality | 5/10 |
| Core Impact | 4/10 |
| Overall | 5/10 |

## Summary

Broad 8-issue submission from an automated agent. All claims are structurally verified against the snapshot, with #2 (split-brain batch reporters), #4 (guardrail fail-open), and #5 (make_lang_run aliasing) being the strongest findings. However, #1 overstates severity by ignoring existing backup/warning mitigations, several issues overlap with prior submissions (S003, S006), and the breadth-over-depth approach means no single finding reaches the insight level of focused submissions. Real issues, presented with limited understanding of design context.

## Why Desloppify Missed This

- **What should catch:** Coupling/structural detectors could flag duplicate implementations (_build_progress_reporter vs BatchProgressTracker); boundary violation detectors could flag imports from `_`-prefixed internal packages.
- **Why not caught:** Desloppify detects code smells at the file/function level, not cross-module duplication or import boundary violations. Fail-open patterns and mutable aliasing are design-level concerns outside current detector scope.
- **What could catch:** A "boundary enforcement" detector checking that `_`-prefixed packages are only imported by their parent; a "duplicate implementation" detector comparing function/method signatures and bodies across modules; a "fail-open audit" that flags catch-all exception handlers in safety-critical paths.
