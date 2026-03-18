# Work Queue

How items get from scan results into the execution queue that `desloppify next` returns.

## Lifecycle phases

The queue shows different items depending on which lifecycle phase the plan is in.
Phase is determined by `_phase_for_snapshot()` and `_legacy_phase_inference()`.

1. **PHASE_REVIEW_INITIAL** — fresh boundary (first scan or cycle reset), no scores yet.
   Shows subjective review items ("review these dimensions"). Objective items are NOT
   visible. Users must complete initial review before seeing the execution queue.

2. **PHASE_EXECUTE** — the main work phase. Shows objective (mechanical defect) items.
   This is where test_coverage, dead_code, naming, etc. appear.

3. **PHASE_SCAN** / **PHASE_*_POSTFLIGHT** — workflow items (rescan, communicate score,
   assessment, triage). These gate the execution phase.

Most users reach PHASE_EXECUTE after the initial review completes and scores are seeded.

## The two queue modes (within PHASE_EXECUTE)

The execution queue operates differently depending on whether triage has run:

### Pre-triage (no plan or empty `queue_order`)

ALL mechanical defect issues are executable. Every open issue from every detector
(test_coverage, dead_code, naming, smells, etc.) goes into the queue. Sorted by:

1. **Impact** (`per_point × headroom`) — issues in low-scoring dimensions sort first
   because they have the most headroom to improve
2. **Confidence** — higher confidence issues sort before lower
3. **Count** — issues affecting more locations sort first

This means whichever dimension has the lowest score AND the most issues dominates
the queue. In practice, test_coverage often floods the queue because:
- It generates one issue per untested file (high volume)
- Most codebases start with low test coverage (high headroom)
- Every issue is high confidence

**Autofix vs manual has no effect on individual item ordering.** The `action_type`
priority (auto_fix > refactor > manual_fix) only applies to cluster-level ordering
after `collapse_clusters`, not to individual issue ranking.

### Post-triage (`queue_order` populated)

Only issues explicitly listed in `plan["queue_order"]` are executable. Everything
else drops to the backlog. Triage (observe → reflect → organize → enrich) decides
what goes in and in what order.

The gate is `executable_objective_ids()` in `schema/__init__.py:310`:
- No `queue_order` → all objective IDs executable (pre-triage mode)
- `queue_order` has entries matching objectives → only those are executable
- `queue_order` has entries but none match objectives → empty execution queue

## Module map

```
snapshot.py          build_queue_snapshot() — the main entry point
  → ranking.py       build_issue_items() — creates WorkQueueItem dicts from state
  → selection.py     items_for_visibility() — filters by execution/backlog view
  → finalize.py      finalize_queue() — enriches with impact, stamps plan position, sorts
  → plan_order.py    stamp_plan_sort_keys(), collapse_clusters()
  → synthetic.py     build_subjective_items(), build_triage_stage_items()
  → synthetic_workflow.py  workflow items (scan, review, communicate-score, deferred)
```

## Sort order (`item_sort_key` in ranking.py)

```
Tier 0: _TIER_PLANNED   — items with explicit plan position (by plan_pos)
Tier 1: _TIER_EXISTING  — known items without plan position (by natural sort)
Tier 2: _TIER_NEW       — newly discovered items (by natural sort)

Natural sort (within each tier):
  _RANK_CLUSTER=0 → clusters first, by action_type (auto_fix=0, refactor=1, manual_fix=2)
  _RANK_ISSUE=1   → individual issues, by -impact, confidence, -count, id
```

## Key types

- `WorkQueueItem` (types.py) — TypedDict with id, kind, detector, file, etc.
- `QueueSnapshot` (models.py) — the full snapshot: execution_items, backlog_items, phase, counts
- `_Partitions` (snapshot.py) — intermediate grouping before phase resolution

## Tier field on issues

The `tier` field (1-4) on individual issues is **display metadata only**. It appears
in `plan` table output as T1/T2/T3/T4 and contributes to narrative dimension
weighting, but does NOT affect queue ordering. The sort key uses impact, not tier.
