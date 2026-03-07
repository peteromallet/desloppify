# S007 Verification: @agustif — review packet construction drift across pipelines

## Status: YES

## Summary

S007 claims that `review` packet construction is duplicated across three independent pipelines
(`prepare.py`, `batch/orchestrator.py`, `external.py`) that bypass a canonical packet builder
(`packet/build.py`), with two concrete examples of schema/policy drift already present.

All four claims are **technically accurate** against snapshot `6eb2065`. The drift is real,
confirmed, and represents a structural maintenance hazard.

## Claims Verified

### Claim 1: Packet assembly is duplicated in three paths
**ACCURATE** — All three files independently call `review_mod.prepare_holistic_review()` and
assemble packet metadata (narrative, config, next_command) inline:
- `prepare.py:41-70` — `do_prepare()` builds packet directly
- `batch/orchestrator.py:120-160` — `_load_or_prepare_packet()` builds packet directly
- `external.py:130-160` — `_prepare_packet_snapshot()` builds packet directly

### Claim 2: Canonical builder exists but is bypassed
**ACCURATE** — `packet/build.py:53-80` defines `build_holistic_packet()` which centralizes
the same logic. `coordinator.py:208+` wraps it with `build_review_packet_payload()` adding
config redaction. None of the three flows above import or use either function.

### Claim 3: `max_files_per_batch` missing from external.py
**ACCURATE** — `prepare.py:55` passes `max_files_per_batch=coerce_review_batch_file_limit(config)`.
`orchestrator.py:149` does the same. `external.py` omits it entirely from
`HolisticReviewPrepareOptions`, meaning external sessions use the library default instead of
the user's configured batch file limit.

### Claim 4: Config redaction missing from external.py
**ACCURATE** — `prepare.py:70` sets `data["config"] = redacted_review_config(config)`.
`orchestrator.py:155` does the same. `external.py` never calls `redacted_review_config` and
never sets `packet["config"]`, meaning external session packets may leak unredacted config
or simply omit config metadata entirely.

## Drift Summary

| Policy | prepare.py | orchestrator.py | external.py | packet/build.py |
|--------|-----------|-----------------|-------------|-----------------|
| `max_files_per_batch` | :white_check_mark: line 55 | :white_check_mark: line 149 | MISSING | :white_check_mark: line 76 |
| `redacted_review_config` | :white_check_mark: line 70 | :white_check_mark: line 155 | MISSING | N/A (in coordinator) |

## Scores

| Criterion | Score | Reasoning |
|-----------|-------|-----------|
| Significance | 7/10 | Real policy drift with concrete behavioral consequences across execution modes |
| Originality | 8/10 | Novel finding — identifies a systemic duplication pattern with specific drift evidence |
| Core Impact | 6/10 | Affects external review sessions; batch file limits silently differ by execution path |
| Overall | 7/10 | Well-researched, accurate, and identifies a genuine structural maintenance hazard |

## Verdict

**YES** — All claims are technically accurate. The submission identifies a real structural problem:
three independent packet construction pipelines that bypass a canonical builder, with two confirmed
instances of policy drift (`max_files_per_batch` and config redaction both missing from `external.py`).
This is a genuine regression multiplier — any future packet contract change must be synchronized
across four code paths instead of one.

## Why Desloppify Missed This

- **What should catch:** The `dupes` detector or `cross_module_architecture` subjective dimension
- **Why not caught:** The duplication is semantic (same logic pattern) not syntactic (identical code).
  Each flow has slightly different surrounding code, making structural duplicate detection miss it.
  The subjective review would need to sample all three files and recognize the shared pattern.
- **What could catch:** A custom detector for "functions that call the same library entry point
  with overlapping parameter assembly" or a review dimension specifically targeting
  "canonical path bypass" patterns.
