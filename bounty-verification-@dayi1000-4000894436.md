# Bounty Verification: S015 @dayi1000 — False Immutability in Dimension.detectors

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4000894436
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `Dimension.detectors: list[str]` inside `@dataclass(frozen=True)`
**CONFIRMED.** At `core.py:20-24`, the `Dimension` dataclass uses `frozen=True` with `detectors: list[str]`. The `frozen` decorator prevents attribute reassignment but does not prevent in-place mutation of the list contents.

### 2. `_build_dimensions()` passes the same list objects from `grouped[name]` directly
**CONFIRMED.** At `core.py:125`, `grouped[name]` (a plain `list[str]`) is passed directly into `Dimension(detectors=grouped[name])`. However, `grouped` is a local variable, so each dimension gets its own list — there is no shared aliasing between dimensions.

### 3. Any code path can mutate `dim.detectors` and corrupt scoring constants
**TECHNICALLY TRUE BUT NOT EXPLOITED.** Verified all usage sites at the snapshot commit across 10+ files:
- `dimension_views.py:71,87` — iteration, `", ".join()`
- `scope.py:125,139` — `list(dim.detectors)` copy for read
- `render.py:181` — iteration
- `core.py:59` (results) — iteration
- `impact.py:23,45` — `in` membership check, iteration

**No code mutates the detectors list in place.** All access is read-only.

### 4. Suggested fix: `detectors: tuple[str, ...]`
**VALID.** This would enforce true immutability and enable hashability. It is indeed a one-line change.

## Duplicate Check
No other submission covers this specific `frozen=True` + mutable container issue. S012 covers `Issue.detail: dict[str, Any]` (a different problem). Not a duplicate.

## Assessment
The observation is technically correct: `list[str]` inside a `frozen=True` dataclass is a false safety contract. The fix is trivial and the finding demonstrates genuine understanding of Python dataclass semantics.

However, significant caveats apply:
1. **No actual mutation occurs**: Every usage site is read-only. The vulnerability is theoretical.
2. **Low blast radius**: Even if someone did mutate `dim.detectors`, the `_rebuild_derived()` function rebuilds all dimensions from scratch, limiting the persistence of corruption to a single rebuild cycle.
3. **Common Python pattern**: Using `list` in frozen dataclasses is widespread in Python codebases and rarely causes real bugs.
4. **Trivial fix**: A one-line change to `tuple[str, ...]` — the simplicity of the fix reflects the simplicity of the issue.
