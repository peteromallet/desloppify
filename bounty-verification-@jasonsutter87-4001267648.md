# Bounty Verification: S024 @jasonsutter87 — Selective Lock Discipline in Parallel Batch Runner

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4001267648
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `started_at` dict: locked on write but read without lock in heartbeat
**PARTIALLY TRUE.** `_run_parallel_task` writes `started_at[idx]` under lock. In `_heartbeat`, the `in started_at` membership check is done under lock, but the `started_at.get(idx, ...)` call for elapsed-time computation is not locked. However, `_heartbeat` runs from the main thread (called by `_drain_parallel_completions`), and under CPython's GIL, `dict.get()` is atomic. The worst case is a slightly stale elapsed-time value — functionally harmless.

### 2. `progress_failures` set: properly locked via `_record_progress_error`
**CONFIRMED.** `_record_progress_error` wraps `progress_failures.add(idx)` in `with lock:`.

### 3. `failures` set: never locked — mutated from multiple threads
**INCORRECT.** This is the submission's core claim, and it is wrong. Tracing every call site:

- `_queue_parallel_tasks` → `failures.add(idx)` — runs in the **main thread** (submits futures, doesn't run in workers)
- `_complete_parallel_future` → `failures.add(idx)` — called by `_drain_parallel_completions`, which iterates `as_completed()` in the **main thread**
- `_record_execution_error` → `failures.add(idx)` — called from `_complete_parallel_future`, again the **main thread**

Worker threads only execute `_run_parallel_task`, which returns an int exit code and **never touches `failures`**. The `failures` set is single-threaded; no lock is needed.

### 4. `contract_cache` dict: never locked — read/written from multiple threads
**PARTIALLY TRUE.** `_progress_contract` reads/writes `contract_cache` without locking, and it is called from worker threads (via `_run_parallel_task` → `_emit_progress`). However, this is a simple idempotent cache: `id(progress_fn)` → `"event"`. Under CPython's GIL, dict operations are thread-safe, and the worst case is a redundant computation storing the same value. This is benign.

### 5. The cited code pattern (lines 249-252)
**PATTERN EXISTS, ANALYSIS WRONG.** The code:
```python
with lock:
    had_progress_failure = idx in progress_failures  # locked
if code != 0 or had_progress_failure:
    failures.add(idx)                                # unlocked
```
does exist in `_complete_parallel_future`. But this function runs in the main thread only (via `as_completed` iteration), so the unlocked `failures.add` is correct — there's no concurrent access to protect against.

## Duplicate Check
No prior submissions cover this specific threading analysis of the parallel batch runner.

## Assessment
The submission demonstrates familiarity with concurrent programming concepts but fundamentally misidentifies the threading model. It assumes `_complete_parallel_future` runs in worker threads, but it actually runs in the main thread (the one iterating `as_completed()`). Only `_run_parallel_task` runs in worker threads, and that function never touches `failures`.

The `started_at` and `contract_cache` observations are technically valid (unlocked cross-thread access) but benign under CPython's GIL and don't represent real bugs or poor engineering — they're standard Python patterns for GIL-protected data structures.

The claim of "worse than no locking at all" is unsupported: the lock discipline is actually consistent — it protects state that IS accessed from worker threads (`started_at` write, `progress_failures`) and doesn't wrap state that's only accessed from the main thread (`failures`).
