# Bounty Verification: S188 @ufct

## Claim

`_DetectorNamesCacheCompat` in `cli.py` is dead production code — a full dict-interface class maintained solely so legacy tests can poke a `_DETECTOR_NAMES_CACHE` global. Production caching uses `@lru_cache` on `_get_detector_names_cached()` and never reads from `_DETECTOR_NAMES_CACHE`.

## Evidence

Verified at commit `6eb2065`:

- **`cli.py:28-45`** — `_DetectorNamesCacheCompat` implements `__contains__`, `__getitem__`, `__setitem__`, `pop`.
- **`cli.py:47`** — `_DETECTOR_NAMES_CACHE = _DetectorNamesCacheCompat()` — global instance.
- **`cli.py:50-52`** — Production cache: `@lru_cache(maxsize=1)` on `_get_detector_names_cached()`.
- **`cli.py:55-57`** — `_get_detector_names()` calls `_get_detector_names_cached()`, never reads `_DETECTOR_NAMES_CACHE`.
- **`cli.py:64`** — Only production usage: `_DETECTOR_NAMES_CACHE.pop("names", None)` in invalidation — a no-op clear of unused state.
- **`tests/commands/test_cli.py:520,530`** — Only consumers: test writes `_DETECTOR_NAMES_CACHE["names"] = ["stale_only"]` and asserts `"names" not in cli_mod._DETECTOR_NAMES_CACHE`.

The class is never read in any production path. The finding is factually correct.

## Duplicate Analysis

| Submission | Author | Created | Same Finding? |
|------------|--------|---------|---------------|
| **S172** | @allornothingai | 2026-03-05T16:13:28Z | YES — identical class, same files, same analysis |
| **S179** | @willtester007-web | 2026-03-05T17:07:28Z | YES — identical |
| **S188** | @ufct | 2026-03-05T20:03:50Z | YES — this submission |
| **S220** | @g5n-dev | 2026-03-06T08:01:05Z | YES — same area, threading angle |

S172 was submitted ~4 hours before S188 with the same core finding.

## Verdict: **NO** — duplicate of S172

The finding is valid but not original. S172 identified the same dead code (`_DetectorNamesCacheCompat` / `_DETECTOR_NAMES_CACHE`) first.
