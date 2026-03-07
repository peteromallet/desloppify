# Bounty Verification: S007 — Review packet construction drift

**Submission:** [S007 by @agustif](https://github.com/peteromallet/desloppify/issues/204#issuecomment-4000584962)
**Snapshot commit:** `6eb2065`

## Claims & Evidence

### Claim 1: Three paths bypass the canonical packet builder

**Verified: YES**

A canonical builder exists at `packet/build.py:53` (`build_holistic_packet`), and the coordinator at `coordinator.py:208` (`build_review_packet_payload`) wraps it. However, three other paths construct review packets independently:

- `prepare.py:48` — calls `review_mod.prepare_holistic_review()` directly
- `batch/orchestrator.py:142` — calls `review_mod.prepare_holistic_review()` directly
- `external.py:150` — calls `review_mod.prepare_holistic_review()` directly

Each path duplicates lang setup, narrative computation, option assembly, and post-processing (config injection, next_command).

### Claim 2: `max_files_per_batch` missing in external.py

**Verified: YES**

- `prepare.py:55`: `max_files_per_batch=coerce_review_batch_file_limit(config)` ✓
- `orchestrator.py:149`: `max_files_per_batch=coerce_review_batch_file_limit(config)` ✓
- `external.py:154-160`: **omitted** — `HolisticReviewPrepareOptions` is constructed without `max_files_per_batch`

### Claim 3: Config redaction missing in external.py

**Verified: YES**

- `prepare.py:70`: `data["config"] = redacted_review_config(config)` ✓
- `orchestrator.py:155`: `packet["config"] = redacted_review_config(config)` ✓
- `external.py`: **never sets `packet["config"]`** — raw config could leak unredacted values

## Verdict

All three claims confirmed against snapshot commit `6eb2065`. The canonical builder exists but is bypassed by all three user-facing entrypoints, and the drift is already producing concrete behavioral differences (missing batch limits and config redaction in the external path).

**Final verdict: YES** — real structural maintenance problem with confirmed drift.

## Scores

| Criterion | Score |
|-----------|-------|
| Significance | 7/10 |
| Originality | 8/10 |
| Core Impact | 6/10 |
| Overall | 7/10 |
