# Bounty Verification: S209 @kamael0909 — Thread-safety violation in parallel batch runner

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4009269464
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `failures.add(idx)` called without lock in `_queue_parallel_tasks`
**TRUE BUT IRRELEVANT.** `_queue_parallel_tasks` runs entirely in the **main thread** — it's a sequential loop that submits tasks to the executor. The `failures.add(idx)` at the queue error path executes in the main thread, not in a worker thread. No lock is needed.

### 2. `failures.add(idx)` called without lock in `_complete_parallel_future`
**TRUE BUT IRRELEVANT.** `_complete_parallel_future` is called from `_drain_parallel_completions`, which iterates `as_completed()` in the **main thread**. This also executes in the main thread, not in a worker thread.

### 3. Worker threads access `failures` concurrently
**FALSE.** The worker function `_run_parallel_task` does NOT receive `failures` as a parameter. Its signature accepts only: `idx`, `tasks`, `progress_fn`, `error_log_fn`, `contract_cache`, `max_workers`, `progress_failures`, `started_at`, `lock`, `clock_fn`. The `failures` set is never passed to or accessed by worker threads.

### 4. Pattern inconsistency with `progress_failures`
**MISLEADING.** `progress_failures` needs lock protection because it IS accessed from worker threads (via `_record_progress_error` called from `_run_parallel_task`). `failures` doesn't need lock protection because it's only accessed from the main thread. The different treatment is correct, not inconsistent.

## Thread Access Analysis

| Shared State | Main Thread | Worker Threads | Lock Protected |
|---|---|---|---|
| `failures` | YES (queue + drain) | NO | Not needed |
| `progress_failures` | YES (drain reads) | YES (worker writes) | YES |
| `started_at` | YES (drain reads) | YES (worker writes) | YES |

The execution flow in `execute_batches` is:
1. `_queue_parallel_tasks(...)` — main thread, submits all tasks, may add to `failures`
2. `_drain_parallel_completions(...)` — main thread, consumes completed futures, may add to `failures`

These are **sequential** in the main thread. Workers only run `_run_parallel_task`, which returns an exit code.

## Duplicate Check
- S024 (@jasonsutter87) makes the same incorrect claim about `failures` lacking lock protection. Both submissions misidentify the threading model.

## Assessment
The submission demonstrates a superficial reading of the code: it correctly identifies that `failures.add()` is called outside a lock, but incorrectly assumes this code runs in worker threads. The critical detail — that `_run_parallel_task` does NOT receive the `failures` set — invalidates the entire claim. There is no thread-safety violation.
