# Bounty Verification: S026 @TheSeanLavery — Performance and Consistency Improvements

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4001296680
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. Regex Compilation Inside Loops (`extractors_components.py`, `react.py`)
**PARTIALLY VALID.**

In `extractors_components.py:49-53`, five `re.findall()` calls with string patterns run inside a `for filepath in find_tsx_files(path)` loop. In `react.py:54,61-62`, `re.finditer()` and `re.findall()` with string patterns also run inside per-file loops. Additionally, `effect_re = re.compile(...)` at `react.py:62` is inside the file loop, recompiling per file.

**However**, Python's `re` module maintains an internal LRU cache of up to 512 compiled patterns. Calls like `re.findall(r"useEffect\s*\(", content)` only compile once; subsequent calls hit the cache with a dict lookup. The overhead is a hash-table lookup per call, not a recompilation. The submission's claim that this "churns objects and skips the efficiency of pre-compilation" is **misleading**. Pre-compiling to module-level constants is a micro-optimization worth ~1 dict lookup per call.

Some patterns in `react.py` ARE already compiled outside the file loop correctly: `provider_open` (line 138), `provider_close` (line 139), `hook_re` (line 199), `bool_state_re` (line 363).

### 2. Centralized File IO Caching Bypass
**CONFIRMED.**

`read_file_text()` at `source.py:91` uses the scan-scoped `file_text_cache`. The cache is enabled during detector runs via `enable_file_cache()` at `workflow.py:361`.

At snapshot, only **3 files** in `languages/` use `read_file_text`:
- `private_imports.py`
- `uncalled.py`
- `unused.py` (TypeScript)

Meanwhile, **30+ files** in `languages/` and `app/` use `Path.read_text()` directly, bypassing the active cache. Key examples in detectors that run during scan:
- `extractors_components.py` (two functions both call `p.read_text()`)
- `react.py` (four detector functions call `p.read_text()`)
- `mutable_state.py`, `responsibility_cohesion.py`, `facade.py`, `deps.py`, `deps_dynamic.py`, `coupling_contracts.py`, `unused_enums.py`, `dict_keys/__init__.py`, `smells_ast/_source_detectors.py`, `smells_runtime.py`
- TypeScript: `concerns.py`, `deprecated.py`, `facade.py`
- C#: `deps_support.py`, `extractors.py`

This is a valid observation. When multiple detectors scan the same files, each re-reads from disk instead of hitting the in-memory cache.

**Caveat:** The OS file system cache mitigates the actual I/O impact. The real cost is repeated string allocation and encoding, not disk reads.

### 3. AST Parsing Caching
**CONFIRMED.**

12 files in `desloppify/languages/python/detectors/` call `ast.parse` independently:
`coupling_contracts.py`, `deps.py` (2x), `deps_dynamic.py`, `dict_keys/__init__.py` (2x), `facade.py`, `mutable_state.py` (2x), `private_imports.py`, `responsibility_cohesion.py`, `smells_ast/_dispatch.py`, `smells_ast/_source_detectors.py` (3x), `uncalled.py`, `unused_enums.py`.

No shared AST cache exists for Python's `ast` module. The codebase does have a tree-sitter parse cache (`_cache.py`) for TS/CSS/etc., but nothing equivalent for Python AST. When a scan runs all Python detectors on the same file set, each detector re-parses every .py file independently.

This is the **most impactful** of the three claims — `ast.parse` is CPU-intensive, and caching would yield measurable savings on large codebases.

## Duplicate Check
No prior submission covers this exact combination of performance issues. Some overlap with general "use the cache" ideas but no direct duplicate.

## Assessment

All three observations point to real inefficiencies in the codebase. The file-IO bypass and AST re-parsing are genuinely impactful during full scans. The regex claim is the weakest — Python's internal regex cache makes the overhead negligible.

**Caveats:**
1. **Regex claim overstated**: Python's `re` module caches compiled patterns; the actual overhead is a dict lookup, not recompilation.
2. **Plan only, no code**: The submission describes what to do but provides zero implementation. The actual difficulty lies in correctly wiring the caches without introducing stale-data bugs.
3. **OS-level mitigation**: File system cache reduces actual disk I/O impact of the `read_file_text` bypass.
4. **Not bugs**: These are optimization opportunities, not correctness issues. The code works correctly as-is.
