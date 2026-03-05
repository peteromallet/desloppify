# Bounty S26 Verification: @xinlingfeiwu submission

## Claim: 57 private imports from app/ bypassing engine facades

### Verdict: NOT VERIFIED — count is grossly inflated

### Findings

The submission claims 57 private imports from `app/` bypassing engine facades.
Actual count: **5 imports across 3 files**.

#### Actual private-module imports from `app/` into `engine._*`:

| File | Line | Import | Available via facade? |
|------|------|--------|-----------------------|
| `app/commands/plan/_resolve.py` | 5 | `engine._plan.schema.PlanModel` | Yes — `engine.plan.PlanModel` |
| `app/commands/plan/_resolve.py` | 6 | `engine._state.resolution.match_findings` | Yes — `state.match_findings` |
| `app/commands/plan/_resolve.py` | 7 | `engine._state.schema.StateModel` | Yes — `state.StateModel` |
| `app/commands/scan/scan_workflow.py` | 482 | `engine._plan.auto_cluster.auto_cluster_findings` | Yes — `engine.plan.auto_cluster_findings` |
| `app/commands/review/preflight.py` | 13 | `engine._work_queue.core.QueueBuildOptions, build_work_queue` | Yes — `engine.work_queue.*` |

#### Facade architecture (confirmed working correctly):

- `desloppify/engine/plan.py` — facade for `engine._plan/` (47 re-exports in `__all__`)
- `desloppify/engine/work_queue.py` — facade for `engine._work_queue/` (24 re-exports in `__all__`)
- `desloppify/state.py` — facade for `engine._state/` (re-exports `StateModel`, `match_findings`, etc.)

All 5 bypassing imports have equivalent facade paths available.

#### Where do the other private imports live?

Total files with `engine._*` imports: 36, but breakdown:
- 17 files are `engine/_*` internal cross-references (expected — modules within the private package)
- 3 files are facade modules themselves (`engine/plan.py`, `engine/work_queue.py`, `state.py`)
- 7 files are tests
- 2 files are `scoring.py` / `languages/` (separate concern)
- 3 files are in `app/` (the actual violations) with 5 total import lines

### Assessment

| Criterion | Rating |
|-----------|--------|
| Accuracy of count | Very low — claimed 57, actual 5 |
| Files/lines exist | Yes — all 5 referenced files exist |
| Real issue? | Minor — 5 imports could route through facades |
| Significance | Low — cosmetic layering issue, no runtime impact |
| Originality | Low — trivially discoverable with a single grep |
| Core impact | None — no bugs, no security issues, no performance impact |

### Recommendation

**Reject the bounty.** The claimed count of 57 is off by more than 10x. The actual
5 facade-bypassing imports are a real but minor layering concern with zero runtime
impact. This does not meet the threshold for a bounty award.
