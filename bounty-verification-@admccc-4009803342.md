# Bounty Verification: S217 @admccc — registry.py God Object Claim

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4009803342
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. DetectorMeta couples display, scoring, planning, queueing, and review concerns
**CONFIRMED.** `DetectorMeta` at `base/registry.py:45-56` has 12 fields spanning multiple axes:
- **Identity/display**: `name`, `display`, `structural`
- **Scoring**: `dimension`, `tier`
- **Planning/action**: `action_type`, `fixers`, `tool`, `guidance`
- **Queue behavior**: `standalone_threshold`
- **LLM routing**: `needs_judgment`
- **Review invalidation**: `marks_dims_stale`

### 2. Registry is imported across engine, scoring, queueing, narrative, and CLI layers
**CONFIRMED.** 20+ production files import from `base/registry.py`:
- Engine layer: `_plan/auto_cluster_sync.py`, `_scoring/policy/core.py`, `_work_queue/ranking.py`, `concerns.py`, etc.
- CLI/app layer: `cli.py`, `scan/reporting/dimensions.py`, `status/render_dimensions.py`
- Narrative layer: `intelligence/narrative/_constants.py`
- Base/output layer: `base/output/issues.py`

### 3. "Detector changes are no longer local"
**PARTIALLY CONFIRMED.** Adding a new detector requires specifying all 12 fields in one place, which does touch all these axes at once. However, the registry is purely declarative data — adding a detector doesn't require modifying any of the consuming modules. The consuming modules derive their behavior from the registry data. This is the intended design.

### 4. "God object for unrelated policy"
**OVERSTATED.** `registry.py` is a data-only module:
- `DetectorMeta` is a `frozen` dataclass (immutable, no methods)
- The module has ~6 small functions: `detector_names()`, `display_order()`, `dimension_action_type()`, `detector_tools()`, `register_detector()`, `reset_registered_detectors()`
- No business logic lives here — behavior is implemented by consumers
- A "god object" typically refers to a class with too many methods and responsibilities, not a configuration table

## Duplicate Check
- S028 (@dayi1000) mentions `registry.py` but focuses on the stale `JUDGMENT_DETECTORS` import binding bug — a distinct finding about Python import semantics, not the registry-as-god-object pattern.
- S071 (@sungdark) covers broad architecture issues but doesn't specifically identify the DetectorMeta coupling pattern.
- No direct duplicate found.

## Assessment
The factual observations are correct: `DetectorMeta` does span multiple behavioral axes, and the registry is imported broadly. However, the "god object" framing overstates the problem:

1. **Registry pattern, not god object**: This is a well-known centralized metadata pattern. The registry holds *data*, not *behavior*. Consumers implement their own logic using the metadata.
2. **Centralization is intentional**: The module docstring explicitly states "single source of truth." The alternative — scattering detector config across scoring, queueing, display, and review modules — would create configuration drift and require N-file updates to add a detector.
3. **No runtime cost**: The coupling doesn't cause bugs, runtime failures, or performance issues. It's a maintainability trade-off.
4. **Frozen dataclass**: `DetectorMeta` is immutable and has zero methods — the opposite of a god object's behavior-rich surface.

The submission correctly identifies the coupling, but mischaracterizes a deliberate, pragmatic design choice as poor engineering.
