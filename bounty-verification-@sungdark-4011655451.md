# Bounty Verification: S244 @sungdark — Global Mutable Singleton State

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4011655451
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `registry.py` uses mutable global `_RUNTIME` singleton
**CONFIRMED.** `base/registry.py:397` creates `_RUNTIME = _RegistryRuntime(...)`, a module-level mutable dataclass holding `detectors`, `display_order`, `callbacks`, and `judgment_detectors`. `register_detector()` (line 418) mutates this global directly, and `reset_registered_detectors()` (line 434) exists specifically to reset it.

### 2. `register_detector()` modifies global state directly
**CONFIRMED.** Lines 418-428 mutate `_RUNTIME.detectors`, `_RUNTIME.display_order`, and `_RUNTIME.judgment_detectors` via a `global JUDGMENT_DETECTORS` rebinding.

### 3. `config.py` has no explicit config instance, uses global implicit context from cwd
**OVERSTATED.** `config.py` has zero `global` statements and no module-level mutable state. `load_config()` and `save_config()` are pure functions that accept an explicit `path` parameter (defaulting to `_default_config_file()` which derives from `get_project_root()`). This is standard CLI tool design — file-based config loaded on demand, not a global mutable singleton.

### 4. "Makes parallel execution impossible and breaks test isolation"
**PARTIALLY VALID but already mitigated.** `reset_registered_detectors()` exists precisely for test isolation and is used in test fixtures and `_framework/discovery.py`. The parallel execution concern is theoretical — desloppify is a CLI tool, not a library intended for concurrent in-process use.

## Duplicate Check
- **S028 (@dayi1000)** — Verified YES_WITH_CAVEATS. Identified the stale `JUDGMENT_DETECTORS` import binding bug caused by the same `_RUNTIME` global state mechanism. S028 found a concrete bug caused by this pattern.
- **S217 (@admccc)** — Verified YES_WITH_CAVEATS. Identified `DetectorMeta` coupling multiple concerns in `registry.py`. Different angle but same module.
- **S181 (@1553401156-spec)** — "Global State Anti-Pattern in Registry" — rejected as duplicate of S028.
- **S172 (@allornothingai)** — About `_DETECTOR_NAMES_CACHE` in `cli.py` — different specific target.

S244's core observation (global mutable `_RUNTIME` in registry.py) overlaps substantially with S028 and S181. S028 already identified and was credited for the engineering consequences of this global state. S181 made the same "global state anti-pattern" observation about the same module and was rejected as a duplicate.

## Assessment
The `_RUNTIME` global singleton observation in `registry.py` is factually correct but is a **duplicate of prior findings**:
1. S028 identified and was credited for the concrete bug caused by this global state.
2. S181 made the same "global state anti-pattern in registry" observation and was rejected as duplicate of S028.
3. The `config.py` claim doesn't hold — it has no global mutable state.
4. The "runtime state" claim is vague and unsubstantiated.
5. The parallel execution concern is theoretical for a CLI tool with existing test isolation support.
