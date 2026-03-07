# Bounty Verification: S220 @g5n-dev

## Submission
**Global State + LRU Cache Threading Hazard in cli.py**

Claims that `desloppify/cli.py:56-78` has three entangled global state mechanisms with a thread-unsafe `@lru_cache`, test pollution via callback accumulation, and unnecessary cache invalidation.

## Verification

### Claim 1: lru_cache is not thread-safe — INCORRECT
The submission states: "@lru_cache is not thread-safe for concurrent reads and writes." This is **factually wrong**. CPython's `functools.lru_cache` uses an internal lock (RLock in pure Python, a C-level lock in the C implementation used since Python 3.8). Concurrent reads and writes, including `cache_clear()`, are safe. The worst case is a redundant recomputation, never data corruption or partial reads.

### Claim 2: Cache invalidation fires unnecessarily — INCORRECT
The submission claims the cache "is invalidated by a callback that fires on *any* detector registration, not just the ones that affect the names." But `register_detector()` always adds a new detector to `_RUNTIME.detectors`, which directly changes what `detector_names()` returns. Every registration **does** affect the names. The invalidation is correct and necessary.

### Claim 3: Three entangled global state mechanisms — OVERSTATED
The `_DetectorNamesCacheCompat` is explicitly documented as "Compat shim for tests that poke the legacy detector-name cache." It's a known, labeled compatibility layer. The `@lru_cache` is the actual cache. The callback is the invalidation trigger. This is a standard cache-with-invalidation pattern.

### Claim 4: Test pollution via callback registry — GENERIC
Callback accumulation in `_RUNTIME.callbacks` is a standard observer pattern. This concern applies to virtually any global callback registry and is not specific or actionable criticism of this code.

### Context
This is `cli.py` — a command-line entry point. It is not used as a web server or in multi-threaded production deployments. The stated impact ("non-deterministic failures in production deployment with concurrent requests") is based on a usage scenario that doesn't apply.

## Verdict: NO

The central technical claim (lru_cache thread-unsafety) is factually incorrect. The cache invalidation logic is correct. The remaining observations (redundant compat shim, global callbacks) are minor and well-understood patterns, not poor engineering.
